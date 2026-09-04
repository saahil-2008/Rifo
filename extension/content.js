/**
 * Rifo — Content Script
 *
 * Injected into every web page (except chrome:// and the Web Store, which are
 * excluded in manifest.json).
 *
 * Responsibilities:
 *   1. Listen for "start_verify" from the background worker → show a loading card.
 *   2. Listen for "ws_frame" messages and update the card as frames arrive.
 *   3. Dismiss the card on Escape or a click outside it.
 *
 * The card lives inside a closed Shadow DOM so page CSS cannot affect it and
 * card CSS cannot leak into the page. This is critical on WhatsApp Web, which
 * aggressively resets all styles.
 *
 * Positioning: the card is anchored near the current selection's bounding rect
 * (text) or falls back to bottom-right corner (image, or when there is no
 * selection).
 */

(function () {
  "use strict";

  // ── Constants ────────────────────────────────────────────────────────────────

  const VERDICT_COLORS = {
    genuine:      { bg: "#0f7b50", light: "#d1fae5", text: "#022c22", badge: "#10b981" },
    misleading:   { bg: "#92400e", light: "#fef3c7", text: "#451a03", badge: "#f59e0b" },
    fake:         { bg: "#991b1b", light: "#fee2e2", text: "#450a0a", badge: "#ef4444" },
    manipulated:  { bg: "#5b21b6", light: "#ede9fe", text: "#2e1065", badge: "#8b5cf6" },
    insufficient: { bg: "#374151", light: "#f3f4f6", text: "#111827", badge: "#9ca3af" },
  };

  const STANCE_LABELS = {
    supports: { label: "Supports",  color: "#10b981" },
    refutes:  { label: "Refutes",   color: "#ef4444" },
    neutral:  { label: "Neutral",   color: "#9ca3af" },
  };

  // ── Shadow host setup ────────────────────────────────────────────────────────

  let hostEl = null;
  let shadowRoot = null;
  let cardEl = null;

  function ensureHost() {
    if (hostEl) return;
    hostEl = document.createElement("div");
    hostEl.id = "rifo-host";
    hostEl.style.cssText = [
      "position: fixed",
      "z-index: 2147483647",
      "pointer-events: none",
      "top: 0",
      "left: 0",
      "width: 0",
      "height: 0",
    ].join(";");
    document.body.appendChild(hostEl);
    shadowRoot = hostEl.attachShadow({ mode: "closed" });
  }

  // ── Card HTML + CSS ─────────────────────────────────────────────────────────

  const CARD_CSS = `
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    :host { all: initial; }

    #rifo-card {
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      position: fixed;
      width: 360px;
      max-height: 540px;
      overflow-y: auto;
      background: #0f172a;
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 16px;
      box-shadow:
        0 25px 50px rgba(0,0,0,0.6),
        0 0 0 1px rgba(255,255,255,0.04) inset;
      color: #e2e8f0;
      pointer-events: all;
      transition: opacity 0.2s ease, transform 0.2s ease;
      opacity: 0;
      transform: translateY(8px) scale(0.97);
    }

    #rifo-card.visible {
      opacity: 1;
      transform: translateY(0) scale(1);
    }

    /* Scrollbar */
    #rifo-card::-webkit-scrollbar { width: 4px; }
    #rifo-card::-webkit-scrollbar-track { background: transparent; }
    #rifo-card::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.12); border-radius: 4px; }

    /* Header */
    .rifo-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px 12px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }

    .rifo-logo {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.02em;
      color: #94a3b8;
    }

    .rifo-logo-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      box-shadow: 0 0 8px rgba(139,92,246,0.6);
      animation: pulse-dot 2s ease-in-out infinite;
    }

    @keyframes pulse-dot {
      0%, 100% { opacity: 1; transform: scale(1); }
      50%       { opacity: 0.6; transform: scale(0.85); }
    }

    .rifo-close {
      background: none;
      border: none;
      color: #64748b;
      cursor: pointer;
      width: 28px;
      height: 28px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      font-size: 16px;
      transition: color 0.15s, background 0.15s;
    }

    .rifo-close:hover { color: #e2e8f0; background: rgba(255,255,255,0.08); }

    /* Body */
    .rifo-body { padding: 14px 16px 16px; }

    /* Loading state */
    .rifo-loading {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 14px;
      padding: 24px 0 8px;
    }

    .rifo-spinner {
      width: 36px;
      height: 36px;
      border: 3px solid rgba(139,92,246,0.15);
      border-top-color: #8b5cf6;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin { to { transform: rotate(360deg); } }

    .rifo-loading-text {
      font-size: 13px;
      color: #64748b;
      text-align: center;
      line-height: 1.5;
    }

    .rifo-loading-claim {
      font-size: 12px;
      color: #475569;
      text-align: center;
      font-style: italic;
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      margin-top: 4px;
    }

    /* Extracted claim pill */
    .rifo-claim {
      font-size: 13px;
      font-weight: 500;
      color: #cbd5e1;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: 8px;
      padding: 9px 12px;
      margin-bottom: 12px;
      line-height: 1.5;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
    }

    /* Verdict badge */
    .rifo-verdict-row {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }

    .rifo-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .rifo-badge-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
      opacity: 0.7;
    }

    /* Confidence bar */
    .rifo-confidence {
      flex: 1;
    }

    .rifo-conf-label {
      font-size: 11px;
      color: #64748b;
      margin-bottom: 4px;
      display: flex;
      justify-content: space-between;
    }

    .rifo-conf-bar-bg {
      height: 4px;
      background: rgba(255,255,255,0.08);
      border-radius: 2px;
      overflow: hidden;
    }

    .rifo-conf-bar {
      height: 100%;
      border-radius: 2px;
      transition: width 0.6s cubic-bezier(0.4,0,0.2,1);
    }

    /* Check count */
    .rifo-check-count {
      font-size: 11px;
      color: #64748b;
      margin-bottom: 12px;
    }

    .rifo-check-count span { color: #94a3b8; font-weight: 500; }

    /* Evidence section */
    .rifo-section-title {
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #475569;
      margin-bottom: 8px;
    }

    .rifo-evidence-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 12px;
    }

    .rifo-evidence-item {
      background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 8px;
      padding: 9px 11px;
      text-decoration: none;
      display: block;
      transition: background 0.15s, border-color 0.15s;
    }

    .rifo-evidence-item:hover {
      background: rgba(255,255,255,0.06);
      border-color: rgba(255,255,255,0.1);
    }

    .rifo-ev-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 4px;
    }

    .rifo-ev-domain {
      font-size: 11px;
      font-weight: 600;
      color: #94a3b8;
    }

    .rifo-ev-stance {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      padding: 2px 7px;
      border-radius: 999px;
      background: rgba(255,255,255,0.06);
    }

    .rifo-ev-title {
      font-size: 12px;
      color: #cbd5e1;
      line-height: 1.4;
      margin-bottom: 3px;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }

    .rifo-ev-date {
      font-size: 10px;
      color: #475569;
    }

    /* Explanation */
    .rifo-explanation {
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.7;
      padding: 10px 12px;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 8px;
      margin-bottom: 4px;
      white-space: pre-wrap;
    }

    .rifo-explanation.streaming::after {
      content: '▋';
      animation: blink 1s step-end infinite;
      color: #6366f1;
    }

    @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }

    /* Error state */
    .rifo-error {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      padding: 20px 0 6px;
      text-align: center;
    }

    .rifo-error-icon { font-size: 28px; }

    .rifo-error-title {
      font-size: 13px;
      font-weight: 600;
      color: #fca5a5;
    }

    .rifo-error-msg {
      font-size: 12px;
      color: #64748b;
      line-height: 1.5;
    }

    /* Footer */
    .rifo-footer {
      padding: 0 16px 14px;
      display: flex;
      justify-content: flex-end;
    }

    .rifo-dismiss-btn {
      font-size: 11px;
      font-weight: 500;
      color: #475569;
      background: none;
      border: none;
      cursor: pointer;
      padding: 4px 0;
      transition: color 0.15s;
    }

    .rifo-dismiss-btn:hover { color: #94a3b8; }
  `;

  // ── Utility ──────────────────────────────────────────────────────────────────

  function truncate(str, n) {
    if (!str) return "";
    return str.length > n ? str.slice(0, n) + "…" : str;
  }

  function formatDate(iso) {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleDateString(undefined, {
        year: "numeric", month: "short", day: "numeric",
      });
    } catch { return ""; }
  }

  function fmtCount(n) {
    if (!n) return "0";
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
    if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
    return String(n);
  }

    let lastX = 0;
    let lastY = 0;

    // Capture the exact pixel where the user right-clicks, as a bulletproof fallback.
    // Complex web apps (like WhatsApp Web) often clear the native text selection when right-clicking.
    document.addEventListener("contextmenu", (e) => {
      lastX = e.clientX;
      lastY = e.clientY;
    }, true);

    function getCardPosition() {
      const CARD_W = 360;
      const CARD_H = 400; // approx, card is max-h 540
      const MARGIN = 12;
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      // Default to right-click coordinates instead of bottom-right of screen
      let x = lastX > 0 ? lastX + MARGIN : vw - CARD_W - MARGIN;
      let y = lastY > 0 ? lastY + MARGIN : vh - CARD_H - MARGIN;
      
      // Keep fallback coordinates within viewport bounds
      if (y + CARD_H > vh) y = Math.max(MARGIN, (lastY > 0 ? lastY : vh) - CARD_H - MARGIN);
      x = Math.max(MARGIN, Math.min(x, vw - CARD_W - MARGIN));

    try {
      const active = document.activeElement;
      if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA")) {
        const rect = active.getBoundingClientRect();
        if (rect.width > 0 || rect.height > 0) {
          x = Math.min(rect.left, vw - CARD_W - MARGIN);
          y = rect.bottom + MARGIN;
          if (y + CARD_H > vh) y = rect.top - CARD_H - MARGIN;
          if (y < MARGIN) y = MARGIN;
          x = Math.max(MARGIN, Math.min(x, vw - CARD_W - MARGIN));
        }
      } else {
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const rect = sel.getRangeAt(0).getBoundingClientRect();
          if (rect.width > 0 || rect.height > 0) {
            x = Math.min(rect.left, vw - CARD_W - MARGIN);
            y = rect.bottom + MARGIN;
            if (y + CARD_H > vh) y = rect.top - CARD_H - MARGIN;
            if (y < MARGIN) y = MARGIN;
            x = Math.max(MARGIN, Math.min(x, vw - CARD_W - MARGIN));
          }
        }
      }
    } catch (_) {}

    return { x, y };
  }

  // ── Card state ───────────────────────────────────────────────────────────────

  let state = {
    phase: "idle",      // "loading" | "streaming" | "done" | "error"
    claim: "",
    verdict: null,      // { label, confidence, check_count }
    evidence: [],
    explanation: "",
    error: null,        // { code, message }
    explanationStreaming: false,
  };

  // ── Render ───────────────────────────────────────────────────────────────────

  function renderCard() {
    if (!cardEl) return;

    const body = shadowRoot.querySelector(".rifo-body");
    if (!body) return;

    let html = "";

    if (state.phase === "loading") {
      html = `
        <div class="rifo-loading">
          <div class="rifo-spinner"></div>
          <div>
            <div class="rifo-loading-text">Verifying claim…</div>
            ${state.claim ? `<div class="rifo-loading-claim">${esc(truncate(state.claim, 120))}</div>` : ""}
          </div>
        </div>
      `;

    } else if (state.phase === "error") {
      const err = state.error || {};
      const icon = err.code === "no_claim_found" ? "🔍" : "⚠️";
      html = `
        <div class="rifo-error">
          <div class="rifo-error-icon">${icon}</div>
          <div class="rifo-error-title">${friendlyErrorTitle(err.code)}</div>
          <div class="rifo-error-msg">${esc(err.message || "")}</div>
        </div>
      `;

    } else {
      // streaming or done — show verdict if present
      if (state.claim) {
        html += `<div class="rifo-claim">${esc(state.claim)}</div>`;
      }

      if (state.verdict) {
        const v = state.verdict;
        const colors = VERDICT_COLORS[v.label] || VERDICT_COLORS.insufficient;
        const confPct = Math.round((v.confidence || 0) * 100);

        html += `
          <div class="rifo-verdict-row">
            <div class="rifo-badge"
                 style="background:${colors.light}; color:${colors.bg};">
              <span class="rifo-badge-dot" style="background:${colors.badge};"></span>
              ${esc(v.label.toUpperCase())}
            </div>
            <div class="rifo-confidence">
              <div class="rifo-conf-label">
                <span>Confidence</span><span>${confPct}%</span>
              </div>
              <div class="rifo-conf-bar-bg">
                <div class="rifo-conf-bar"
                     style="width:${confPct}%; background:${colors.badge};"></div>
              </div>
            </div>
          </div>
          <div class="rifo-check-count">
            Checked <span>${fmtCount(v.check_count)}</span> time${v.check_count !== 1 ? "s" : ""}
          </div>
        `;
      }

      if (state.evidence && state.evidence.length) {
        html += `<div class="rifo-section-title">Evidence</div>`;
        html += `<div class="rifo-evidence-list">`;
        state.evidence.slice(0, 5).forEach((ev) => {
          const st = STANCE_LABELS[ev.stance] || { label: ev.stance || "–", color: "#9ca3af" };
          html += `
            <a class="rifo-evidence-item" href="${esc(ev.url || "#")}" target="_blank" rel="noopener noreferrer">
              <div class="rifo-ev-top">
                <span class="rifo-ev-domain">${esc(ev.domain || "")}</span>
                <span class="rifo-ev-stance" style="color:${st.color};">${esc(st.label)}</span>
              </div>
              <div class="rifo-ev-title">${esc(ev.title || "")}</div>
              ${ev.published_at ? `<div class="rifo-ev-date">${esc(formatDate(ev.published_at))}</div>` : ""}
            </a>
          `;
        });
        html += `</div>`;
      }

      if (state.explanation) {
        html += `
          <div class="rifo-section-title">Explanation</div>
          <div class="rifo-explanation ${state.explanationStreaming ? "streaming" : ""}">
            ${esc(state.explanation)}
          </div>
        `;
      }
    }

    body.innerHTML = html;
  }

  function esc(str) {
    if (str == null) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function friendlyErrorTitle(code) {
    const map = {
      no_claim_found: "No verifiable claim found",
      upload_failed:  "Could not load content",
      timeout:        "Request timed out",
      flag_secure:    "Screenshot protected",
    };
    return map[code] || "Something went wrong";
  }

  // ── Show / hide card ─────────────────────────────────────────────────────────

  function showCard() {
    ensureHost();

    if (!cardEl) {
      const style = document.createElement("style");
      style.textContent = CARD_CSS;

      cardEl = document.createElement("div");
      cardEl.id = "rifo-card";

      cardEl.innerHTML = `
        <div class="rifo-header">
          <div class="rifo-logo">
            <div class="rifo-logo-dot"></div>
            Rifo Fact Check
          </div>
          <button class="rifo-close" id="rifo-close-btn" title="Dismiss (Esc)">✕</button>
        </div>
        <div class="rifo-body"></div>
        <div class="rifo-footer">
          <button class="rifo-dismiss-btn" id="rifo-dismiss-btn">Dismiss</button>
        </div>
      `;

      shadowRoot.appendChild(style);
      shadowRoot.appendChild(cardEl);

      // Close button inside shadow root
      shadowRoot.getElementById("rifo-close-btn").addEventListener("click", hideCard);
      shadowRoot.getElementById("rifo-dismiss-btn").addEventListener("click", hideCard);
    }

    // Position near selection
    const { x, y } = getCardPosition();
    cardEl.style.left = x + "px";
    cardEl.style.top  = y + "px";

    // Animate in
    requestAnimationFrame(() => {
      requestAnimationFrame(() => cardEl.classList.add("visible"));
    });

    renderCard();
  }

  function hideCard() {
    if (!cardEl) return;
    cardEl.classList.remove("visible");
    // Remove from DOM after transition
    setTimeout(() => {
      if (cardEl) {
        cardEl.remove();
        cardEl = null;
      }
    }, 220);
    // Reset state
    state = { phase: "idle", claim: "", verdict: null, evidence: [], explanation: "", error: null, explanationStreaming: false };
  }

  // ── Message listeners ────────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
    if (msg.type === "start_verify") {
      // Reset and show loading card
      state = { phase: "loading", claim: "", verdict: null, evidence: [], explanation: "", error: null, explanationStreaming: false };
      showCard();
      return;
    }

    if (msg.type === "ws_frame") {
      const frame = msg.frame;
      handleFrame(frame);
    }
  });

  function handleFrame(frame) {
    switch (frame.stage) {
      case "extracted":
        state.claim = frame.claim || frame.claim_original || "";
        break;

      case "cache_hit":
      case "cache_miss":
        // No visual change needed; loading state continues.
        break;

      case "verdict":
        state.phase = "streaming";
        state.verdict = {
          label:       frame.label,
          confidence:  frame.confidence,
          check_count: frame.check_count,
        };
        break;

      case "evidence":
        state.evidence = Array.isArray(frame.items) ? frame.items : [];
        break;

      case "explanation":
        state.explanationStreaming = true;
        state.explanation = frame.text || "";
        break;

      case "done":
        state.phase = "done";
        state.explanationStreaming = false;
        break;

      case "error":
        state.phase = "error";
        state.error = { code: frame.code, message: frame.message };
        break;

      default:
        return; // Ignore unknown frames
    }

    // Re-render on every frame
    if (state.phase !== "idle") {
      showCard();
    }
  }

  // ── Keyboard / outside-click dismiss ────────────────────────────────────────

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && cardEl) {
      hideCard();
    }
  }, { capture: true });

  document.addEventListener("mousedown", (e) => {
    if (!cardEl) return;
    // Check if the click target is outside the shadow host
    if (!hostEl.contains(e.target)) {
      hideCard();
    }
  }, { capture: true });

})();
