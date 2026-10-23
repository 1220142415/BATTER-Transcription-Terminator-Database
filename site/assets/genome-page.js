(function () {
  "use strict";

  const root = document.querySelector("[data-genome-page]");
  const frame = document.querySelector("[data-browser-frame]");
  if (!root || !frame || !frame.dataset.config) return;

  const assembly = root.dataset.assembly;
  let params = new URLSearchParams(window.location.search);
  const browserUrl = new URL("../jbrowse/index.html", document.baseURI);
  const shareButton = document.querySelector("[data-share-view]");
  const trackButtons = document.querySelectorAll("[data-select-tracks], [data-add-user-track]");
  const shareStatus = document.querySelector("[data-share-status]");
  const shareManual = document.querySelector("[data-share-manual]");
  const browserStatus = document.querySelector("[data-browser-status]");
  const retryBrowser = document.querySelector("[data-retry-browser]");
  const bridgeChannel = "bted-browser-v1";
  let bridgeNonce = "";
  let bridgeReady = false;
  let requestNumber = 0;
  const pending = new Map();
  let loadingTimer;

  function setBrowserStatus(message) {
    if (browserStatus) browserStatus.textContent = message;
  }

  function shareMessage(message) {
    frame.contentWindow?.postMessage({ channel: bridgeChannel, nonce: bridgeNonce, ...message }, window.location.origin);
  }

  function parseSharedView(query) {
    if (!query.has("view")) return null;
    const keys = ["view", "ref", "center", "zoom", "rev", "tracks"];
    if (keys.some((key) => query.getAll(key).length !== 1) || query.get("view") !== "1") throw new Error("Invalid view link.");
    const ref = query.get("ref");
    const center = Number(query.get("center"));
    const zoom = Number(query.get("zoom"));
    const rev = query.get("rev");
    if (!ref || ref.length > 255 || !Number.isSafeInteger(center) || center < 1 ||
        !Number.isFinite(zoom) || zoom <= 0 || !["0", "1"].includes(rev)) throw new Error("Invalid view link.");
    const tracks = query.get("tracks") ? query.get("tracks").split(",").map((entry) => {
      const divider = entry.lastIndexOf(":");
      const id = entry.slice(0, divider);
      const height = Number(entry.slice(divider + 1));
      if (divider < 1 || !/^[A-Za-z0-9_.-]{1,128}$/.test(id) || !Number.isFinite(height) || height < 20 || height > 1000) {
        throw new Error("Invalid track list.");
      }
      return { id, height };
    }) : [];
    if (tracks.length > 100 || new Set(tracks.map((track) => track.id)).size !== tracks.length) throw new Error("Invalid track list.");
    return { version: 1, ref, center, zoom, reversed: rev === "1", tracks };
  }

  function sharedUrl(state) {
    const url = new URL(window.location.href);
    ["view", "ref", "center", "zoom", "rev", "tracks", "session", "loc", "highlight"].forEach((key) => url.searchParams.delete(key));
    url.searchParams.set("view", "1");
    url.searchParams.set("ref", state.ref);
    url.searchParams.set("center", String(state.center));
    url.searchParams.set("zoom", String(state.zoom));
    url.searchParams.set("rev", state.reversed ? "1" : "0");
    url.searchParams.set("tracks", state.tracks.map((track) => `${track.id}:${track.height}`).join(","));
    return url.href;
  }

  function setShareStatus(message) {
    if (shareStatus) shareStatus.textContent = message;
  }

  function showDefaultView() {
    const id = String(++requestNumber);
    pending.set(id, "default");
    shareMessage({ type: "show-default", id });
  }

  window.addEventListener("message", async (event) => {
    const message = event.data;
    if (event.origin !== window.location.origin || event.source !== frame.contentWindow ||
        message?.channel !== bridgeChannel || message.nonce !== bridgeNonce) return;
    if (message.type === "ready") {
      window.clearTimeout?.(loadingTimer);
      bridgeReady = true;
      if (Number.isFinite(message.frameHeight) && message.frameHeight >= 300 && message.frameHeight <= 10000) {
        frame.style.height = `${message.frameHeight}px`;
      }
      setBrowserStatus("");
      if (shareButton) shareButton.disabled = false;
      trackButtons.forEach((button) => { button.disabled = false; });
      try {
        const state = parseSharedView(params);
        if (state) {
          const id = String(++requestNumber);
          pending.set(id, "restore");
          setShareStatus("Restoring shared view…");
          shareMessage({ type: "restore", id, state });
        } else if (params.has("loc")) {
          const id = String(++requestNumber);
          pending.set(id, "navigate");
          shareMessage({ type: "navigate", id, location: params.get("loc") });
        } else if (!["loc", "session", "tracks", "highlight"].some((key) => params.has(key))) {
          setShareStatus("");
          if (!root.dataset.preserveDefaultView) showDefaultView();
        } else setShareStatus("");
      } catch (error) {
        setShareStatus(`${error.message} Default view restored.`);
        showDefaultView();
      }
      return;
    }
    const action = pending.get(message.id);
    if (!action) {
      if (message.type === "error") {
        window.clearTimeout?.(loadingTimer);
        setBrowserStatus(message.message || "Browser unavailable.");
      }
      return;
    }
    pending.delete(message.id);
    if (message.type === "error") {
      setShareStatus(message.message || "View unavailable.");
      if (["navigate", "restore"].includes(action)) {
        setShareStatus(`${message.message || "View unavailable."} Default view restored.`);
        showDefaultView();
      }
    } else if (action === "restore" && message.type === "restored") {
      setShareStatus("Shared view restored.");
    } else if (action === "capture" && message.type === "captured") {
      const url = sharedUrl(message.state);
      try {
        await navigator.clipboard.writeText(url);
        if (shareManual) shareManual.hidden = true;
        setShareStatus(`Link copied.${message.hasUserTracks ? " Imported tracks excluded." : ""}`);
      } catch {
        if (shareManual) {
          shareManual.hidden = false;
          shareManual.value = url;
          shareManual.focus();
          shareManual.select();
        }
        setShareStatus(`Copy link below.${message.hasUserTracks ? " Imported tracks excluded." : ""}`);
      }
    }
  });

  shareButton?.addEventListener("click", () => {
    if (!bridgeReady) return;
    const id = String(++requestNumber);
    pending.set(id, "capture");
    setShareStatus("Preparing view link…");
    shareMessage({ type: "capture", id });
  });

  trackButtons.forEach((button) => button.addEventListener("click", () => {
    if (!bridgeReady) return;
    const id = String(++requestNumber);
    pending.set(id, "panel");
    shareMessage({ type: button.hasAttribute("data-select-tracks") ? "select-tracks" : "add-user-track", id });
  }));

  function selectedSource() {
    return params.get("source_id") || "";
  }

  function showSource(sourceId) {
    document.querySelectorAll("[data-source-card]").forEach((card) => {
      card.classList.toggle("source-highlight", Boolean(sourceId) && card.dataset.sourceCard === sourceId);
    });
  }

  function loadBrowser() {
    // Each iframe load gets a fresh host; stale feature details never survive Reload.
    document.querySelector("[data-browser-feature-details]")?.remove();
    const panel = frame.closest(".browser-panel");
    let workspace = panel.closest(".browser-workspace");
    if (!workspace) {
      workspace = document.createElement("div");
      workspace.className = "browser-workspace";
      panel.before(workspace);
      workspace.append(panel);
    }
    const details = document.createElement("aside");
    details.className = "browser-feature-details";
    details.dataset.browserFeatureDetails = "";
    details.hidden = true;
    details.setAttribute("aria-labelledby", "browser-feature-details-heading");
    details.innerHTML = '<div class="browser-feature-details-heading"><h2 id="browser-feature-details-heading">Feature details</h2><button type="button" data-close-feature-details aria-label="Close feature details">Close <span aria-hidden="true">×</span></button></div><p class="browser-widget-note" data-browser-widget-note hidden></p><div data-feature-details-content></div>';
    const shadow = details.querySelector("[data-feature-details-content]").attachShadow({ mode: "open" });
    const widgetHost = document.createElement("div");
    widgetHost.dataset.nativeFeatureDetails = "";
    shadow.append(widgetHost);
    workspace.append(details);
    window.clearTimeout?.(loadingTimer);
    setBrowserStatus("Loading browser…");
    setShareStatus("");
    loadingTimer = window.setTimeout?.(() => {
      if (!bridgeReady) setBrowserStatus("Browser loading timed out. Reload to retry.");
    }, 30000);
    bridgeReady = false;
    bridgeNonce = Math.random().toString(36).slice(2);
    if (shareButton) shareButton.disabled = true;
    trackButtons.forEach((button) => { button.disabled = true; });
    if (shareManual) shareManual.hidden = true;
    pending.clear();
    const frameParams = new URLSearchParams();
    const configUrl = new URL(frame.dataset.config, browserUrl);
    configUrl.searchParams.set("v", "41");
    frameParams.set("config", configUrl.href);
    frameParams.set("bted_bridge", bridgeNonce);
    ["session", "tracks", "highlight"].forEach((key) => {
      if (params.has("view")) return;
      const value = params.get(key);
      if (value) frameParams.set(key, value);
    });
    // Keep JBrowse's default session intact: it includes separate endpoint,
    // reference and, where available, +/− experimental signal tracks.
    frame.src = `${browserUrl.href}?${frameParams.toString()}`;
  }

  showSource(selectedSource());
  loadBrowser();
  retryBrowser?.addEventListener("click", loadBrowser);

  window.addEventListener("popstate", () => {
    params = new URLSearchParams(window.location.search);
    showSource(selectedSource());
    loadBrowser();
  });

})();
