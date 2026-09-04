"""Gemini Search Grounding service for evidence retrieval.

Uses Google GenAI SDK to perform a grounded web search,
returning factual summaries and extracted URL citations.
"""

import os
import logging
import datetime
from typing import List, Dict

from google import genai
from google.genai import types
from app.config import settings

logger = logging.getLogger(__name__)

# Cache client globally if possible, but we instantiate here to be safe
_client = None

def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY", settings.gemini_api_key if hasattr(settings, 'gemini_api_key') else None)
        _client = genai.Client(api_key=api_key)
    return _client

async def search_grounded(query: str, count: int = 5) -> List[Dict]:
    """
    Search the web using Gemini's Search Grounding tool.
    
    Args:
        query: The fact-check claim or query string.
        count: (Ignored for now, as Gemini controls chunk count).
        
    Returns:
        List of evidence-shaped dicts with url, domain, title, snippet.
    """
    logger.info("gemini_search: querying Gemini with Google Search Grounding for '%s'", query[:60])
    
    client = get_client()
    
    try:
        # We use sync generate_content in an executor or async if available. 
        # google.genai provides async via client.aio
        response = await client.aio.models.generate_content(
            model='gemini-3.6-flash',
            contents=f"Please verify this claim by searching the web. Be highly accurate and provide the facts: {query}",
            config=types.GenerateContentConfig(
                tools=[{'google_search': {}}],
                temperature=0.1,
            )
        )
        
        # Parse the grounded response
        summary_text = response.text or ""
        
        results = []
        seen_urls = set()
        
        metadata = None
        if response.candidates and response.candidates[0].grounding_metadata:
            metadata = response.candidates[0].grounding_metadata
            
        if metadata and hasattr(metadata, 'grounding_chunks'):
            for chunk in metadata.grounding_chunks:
                if hasattr(chunk, 'web') and chunk.web:
                    url = chunk.web.uri
                    title = chunk.web.title or "Grounded Source"
                    
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        
                        # Extract domain
                        domain = url.split("//")[-1].split("/")[0]
                        
                        results.append({
                            "url": url,
                            "domain": domain,
                            "title": title,
                            # We use the whole response text as the snippet for context
                            "snippet": summary_text,
                            "stance": "",
                            "stance_score": 0.0,
                            "published_at": datetime.datetime.utcnow().isoformat(),
                            "credibility": 0.8,
                        })
        
        # If no chunks were returned but we have text, return a generic item
        if not results and summary_text:
            results.append({
                "url": "https://google.com/search?q=" + query.replace(" ", "+"),
                "domain": "google.com",
                "title": "Google Search via Gemini",
                "snippet": summary_text,
                "stance": "",
                "stance_score": 0.0,
                "published_at": datetime.datetime.utcnow().isoformat(),
                "credibility": 0.8,
            })
            
        logger.info("gemini_search: returned %d grounded sources", len(results))
        return results

    except Exception as e:
        logger.warning("gemini_search: grounded search failed for '%s': %s", query[:60], e)
        # Re-raise 429 so the user can see it during demo if needed, or return empty?
        # Graph retrieve node handles empty list gracefully, but since user specifically
        # knows about 429, let's log and return empty so pipeline continues or let's 
        # return a dummy 429 result so UI shows something.
        
        if "429" in str(e):
             logger.error("QUOTA EXCEEDED FOR GEMINI KEY")
             # Return a fallback to indicate quota error if possible
        
        return []

