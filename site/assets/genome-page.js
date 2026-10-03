(function () {
  "use strict";

  const root = document.querySelector("[data-genome-page]");
  const frame = document.querySelector("[data-browser-frame]");
  if (!root || !frame || !frame.dataset.config) return;

  const assembly = root.dataset.assembly;
  let params = new URLSearchParams(window.location.search);
  const browserUrl = new URL("../jbrowse/index.html", document.baseURI);
  const shareButton = document.querySelector("[data-share-view]");
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
    if (keys.some((key) => query.getAll(key).length !== 1) || query.get("view") !== "1") throw new Error("This shared view link is invalid.");
    const ref = query.get("ref");
    const center = Number(query.get("center"));
    const zoom = Number(query.get("zoom"));
    const rev = query.get("rev");
    if (!ref || ref.length > 255 || !Number.isSafeInteger(center) || center < 1 ||
        !Number.isFinite(zoom) || zoom <= 0 || !["0", "1"].includes(rev)) throw new Error("This shared view link is invalid.");
    const tracks = query.get("tracks") ? query.get("tracks").split(",").map((entry) => {
      const divider = entry.lastIndexOf(":");
      const id = entry.slice(0, divider);
      const height = Number(entry.slice(divider + 1));
      if (divider < 1 || !/^[A-Za-z0-9_.-]{1,128}$/.test(id) || !Number.isFinite(height) || height < 20 || height > 1000) {
        throw new Error("This shared view has an invalid track list.");
      }
      return { id, height };
    }) : [];
    if (tracks.length > 100 || new Set(tracks.map((track) => track.id)).size !== tracks.length) throw new Error("This shared view has an invalid track list.");
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
      setBrowserStatus("");
      if (shareButton) shareButton.disabled = false;
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
          showDefaultView();
        } else setShareStatus("");
      } catch (error) {
        setShareStatus(`${error.message} Showing the default view.`);
        showDefaultView();
      }
      return;
    }
    const action = pending.get(message.id);
    if (!action) {
      if (message.type === "error") {
        window.clearTimeout?.(loadingTimer);
        setBrowserStatus(`${message.message || "Browser unavailable."} Select Reload to retry.`);
      }
      return;
    }
    pending.delete(message.id);
    if (message.type === "error") {
      setShareStatus(message.message || "The browser view is unavailable.");
      if (["navigate", "restore"].includes(action)) {
        setShareStatus(`${message.message || "The browser view is unavailable."} Showing the default view.`);
        showDefaultView();
      }
    } else if (action === "restore" && message.type === "restored") {
      setShareStatus("Shared view restored.");
    } else if (action === "capture" && message.type === "captured") {
      const url = sharedUrl(message.state);
      try {
        await navigator.clipboard.writeText(url);
        if (shareManual) shareManual.hidden = true;
        setShareStatus("View link copied.");
      } catch {
        if (shareManual) {
          shareManual.hidden = false;
          shareManual.value = url;
          shareManual.focus();
          shareManual.select();
        }
        setShareStatus("Copy the link shown below.");
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

  function selectedSource() {
    return params.get("source_id") || "";
  }

  function showSource(sourceId) {
    document.querySelectorAll("[data-source-card]").forEach((card) => {
      card.classList.toggle("source-highlight", Boolean(sourceId) && card.dataset.sourceCard === sourceId);
    });
  }

  function loadBrowser() {
    window.clearTimeout?.(loadingTimer);
    setBrowserStatus("Loading browser…");
    setShareStatus("");
    loadingTimer = window.setTimeout?.(() => {
      if (!bridgeReady) setBrowserStatus("The browser is taking longer than expected. Select Reload to retry.");
    }, 30000);
    bridgeReady = false;
    bridgeNonce = Math.random().toString(36).slice(2);
    if (shareButton) shareButton.disabled = true;
    if (shareManual) shareManual.hidden = true;
    pending.clear();
    const frameParams = new URLSearchParams();
    frameParams.set("config", new URL(frame.dataset.config, browserUrl).href);
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

  const packageButton = document.querySelector("[data-download-genome-package]");
  const packageStatus = document.querySelector("[data-package-status]");
  if (!packageButton) return;

  const crcTable = Array.from({ length: 256 }, (_, index) => {
    let value = index;
    for (let bit = 0; bit < 8; bit += 1) value = (value & 1) ? (0xedb88320 ^ (value >>> 1)) : (value >>> 1);
    return value >>> 0;
  });

  function crc32(bytes) {
    let crc = 0xffffffff;
    bytes.forEach((byte) => { crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8); });
    return (crc ^ 0xffffffff) >>> 0;
  }

  function createZip(files) {
    const encoder = new TextEncoder();
    const localParts = [];
    const centralParts = [];
    let localOffset = 0;
    files.forEach((file) => {
      const name = encoder.encode(file.name);
      const data = file.data;
      const checksum = crc32(data);
      const local = new Uint8Array(30 + name.length);
      const localView = new DataView(local.buffer);
      localView.setUint32(0, 0x04034b50, true);
      localView.setUint16(4, 20, true);
      localView.setUint16(6, 0x0800, true);
      localView.setUint16(8, 0, true);
      localView.setUint32(14, checksum, true);
      localView.setUint32(18, data.length, true);
      localView.setUint32(22, data.length, true);
      localView.setUint16(26, name.length, true);
      local.set(name, 30);
      localParts.push(local, data);

      const central = new Uint8Array(46 + name.length);
      const centralView = new DataView(central.buffer);
      centralView.setUint32(0, 0x02014b50, true);
      centralView.setUint16(4, 20, true);
      centralView.setUint16(6, 20, true);
      centralView.setUint16(8, 0x0800, true);
      centralView.setUint16(10, 0, true);
      centralView.setUint32(16, checksum, true);
      centralView.setUint32(20, data.length, true);
      centralView.setUint32(24, data.length, true);
      centralView.setUint16(28, name.length, true);
      centralView.setUint32(42, localOffset, true);
      central.set(name, 46);
      centralParts.push(central);
      localOffset += local.length + data.length;
    });

    const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
    const end = new Uint8Array(22);
    const endView = new DataView(end.buffer);
    endView.setUint32(0, 0x06054b50, true);
    endView.setUint16(8, files.length, true);
    endView.setUint16(10, files.length, true);
    endView.setUint32(12, centralSize, true);
    endView.setUint32(16, localOffset, true);
    return new Blob([...localParts, ...centralParts, end], { type: "application/zip" });
  }

  packageButton.addEventListener("click", async () => {
    const links = Array.from(root.querySelectorAll("[data-package-file][data-zip-path]"));
    packageButton.disabled = true;
    if (packageStatus) packageStatus.textContent = "Preparing the genome package…";
    try {
      const files = await Promise.all(links.map(async (link) => {
        const response = await fetch(link.href, { credentials: "omit" });
        if (!response.ok) throw new Error(`Could not fetch ${link.dataset.zipPath}: ${response.status}`);
        return { name: link.dataset.zipPath, data: new Uint8Array(await response.arrayBuffer()) };
      }));
      if (!files.length) throw new Error("No files are available for this genome.");
      const blob = createZip(files);
      const objectUrl = URL.createObjectURL(blob);
      const download = document.createElement("a");
      download.href = objectUrl;
      download.download = `BTED-v0.4.0-${assembly}.zip`;
      document.body.append(download);
      download.click();
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
      if (packageStatus) packageStatus.textContent = `Created a ZIP with ${files.length} GFF3 and TSV files.`;
    } catch (error) {
      if (packageStatus) packageStatus.textContent = "Package creation failed. Check your connection and try again.";
      console.error(error);
    } finally {
      packageButton.disabled = false;
    }
  });
})();
