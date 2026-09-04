/**
 * Rifo — Background Service Worker (MV3)
 *
 * Responsibilities:
 *   1. Register context menu items on install.
 *   2. On context menu click: send a "start_verify" message to the content
 *      script, open a WebSocket to the backend, relay every streaming frame
 *      back to the tab as a "ws_frame" message.
 *   3. Keep a device_id in chrome.storage.local (generated once, never reset).
 *
 * The service worker is the sole owner of the WebSocket.  Content scripts
 * cannot open WebSockets that survive their own lifecycle; the background
 * worker keeps the connection alive for the duration of a verification.
 *
 * Fails quietly: any error is logged to console and an error frame is sent to
 * the tab so the card can display it rather than spinning forever.
 */

const WS_URL = "ws://127.0.0.1:8000/v1/verify/stream";

// ── Context menu ──────────────────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(() => {
  // Remove stale items first (service worker can be restarted)
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "verify-text",
      title: "Verify this claim",
      contexts: ["selection"],
    });

    chrome.contextMenus.create({
      id: "verify-image",
      title: "Verify this image",
      contexts: ["image"],
    });
  });
});

// ── Device ID ─────────────────────────────────────────────────────────────────

async function getDeviceId() {
  return new Promise((resolve) => {
    chrome.storage.local.get("device_id", (result) => {
      if (result.device_id) {
        resolve(result.device_id);
      } else {
        const id = crypto.randomUUID();
        chrome.storage.local.set({ device_id: id }, () => resolve(id));
      }
    });
  });
}

// ── Context menu click handler ────────────────────────────────────────────────

async function handleVerifyAction(tab, selectionText, srcUrl, menuItemId) {
  if (!tab?.id) return;

  const url = tab.url || "";
  if (
    url.startsWith("chrome://") ||
    url.startsWith("chrome-extension://") ||
    url.startsWith("https://chrome.google.com/webstore")
  ) {
    console.warn("Rifo: cannot inject into privileged page:", url);
    return;
  }

  const deviceId = await getDeviceId();

  try {
    await chrome.tabs.sendMessage(tab.id, {
      type: "start_verify",
      menuItemId: menuItemId,
    });
  } catch (e) {
    console.warn("Rifo: content script not reachable, injecting dynamically...", e);
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content.js"],
      });
      await chrome.tabs.sendMessage(tab.id, {
        type: "start_verify",
        menuItemId: menuItemId,
      });
    } catch (err) {
      console.error("Rifo: failed to dynamically inject:", err);
      return;
    }
  }

  let payload;
  if (menuItemId === "verify-text") {
    const text = (selectionText || "").trim();
    if (!text) {
      sendFrame(tab.id, {
        stage: "error",
        code: "no_claim_found",
        message: "No text selected.",
      });
      return;
    }
    payload = { type: "text", content: text, device_id: deviceId };
  } else if (menuItemId === "verify-image") {
    const src = (srcUrl || "").trim();
    if (!src) {
      sendFrame(tab.id, {
        stage: "error",
        code: "upload_failed",
        message: "Could not read image URL.",
      });
      return;
    }
    payload = { type: "image", image_url: src, device_id: deviceId };
  } else {
    return;
  }

  openVerifyStream(tab.id, payload);
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  handleVerifyAction(tab, info.selectionText, info.srcUrl, info.menuItemId);
});

chrome.action.onClicked.addListener(async (tab) => {
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.getSelection().toString()
    });
    
    if (result && result.trim()) {
      handleVerifyAction(tab, result, null, "verify-text");
    } else {
      handleVerifyAction(tab, "", null, "verify-text");
    }
  } catch (err) {
    console.error("Failed to get selection", err);
  }
});

// ── WebSocket streaming ───────────────────────────────────────────────────────

function sendFrame(tabId, frame) {
  chrome.tabs.sendMessage(tabId, { type: "ws_frame", frame }).catch((e) => {
    // Tab may have been closed or navigated away — ignore silently.
    console.debug("Rifo: could not send frame to tab:", e);
  });
}

function openVerifyStream(tabId, payload) {
  let ws;
  let keepaliveTimer = null;

  // MV3 service workers are killed after 30 s of "inactivity". A running
  // WebSocket doesn't count as activity in all Chrome builds, so we
  // ping chrome.runtime every 20 s to reset the idle timer.
  function startKeepalive() {
    stopKeepalive();
    keepaliveTimer = setInterval(() => {
      chrome.runtime.getPlatformInfo(() => {});
    }, 20_000);
  }

  function stopKeepalive() {
    if (keepaliveTimer) {
      clearInterval(keepaliveTimer);
      keepaliveTimer = null;
    }
  }

  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    console.error("Rifo: could not create WebSocket:", e);
    sendFrame(tabId, {
      stage: "error",
      code: "timeout",
      message: "Could not connect to Rifo backend. Is the server running?",
    });
    return;
  }

  ws.onopen = () => {
    startKeepalive();
    ws.send(JSON.stringify(payload));
  };

  ws.onmessage = (event) => {
    try {
      const frame = JSON.parse(event.data);
      sendFrame(tabId, frame);
      // Close the socket once the terminal frame arrives.
      if (frame.stage === "done" || frame.stage === "error") {
        stopKeepalive();
        ws.close();
      }
    } catch (e) {
      console.error("Rifo: could not parse frame:", e, event.data);
    }
  };

  ws.onerror = (e) => {
    console.error("Rifo: WebSocket error:", e);
    stopKeepalive();
    sendFrame(tabId, {
      stage: "error",
      code: "timeout",
      message: "Connection to Rifo backend failed. Make sure the server is running on localhost:8000.",
    });
  };

  ws.onclose = (e) => {
    stopKeepalive();
    if (!e.wasClean) {
      console.warn("Rifo: WebSocket closed unexpectedly (code=%d)", e.code);
    }
  };
}
