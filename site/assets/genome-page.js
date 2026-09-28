(function () {
  "use strict";

  const root = document.querySelector("[data-genome-page]");
  const frame = document.querySelector("[data-browser-frame]");
  if (!root || !frame || !frame.dataset.config) return;

  const assembly = root.dataset.assembly;
  let params = new URLSearchParams(window.location.search);
  const browserUrl = new URL("../jbrowse/index.html", document.baseURI);

  function selectedSource() {
    return params.get("source_id") || "";
  }

  function showSource(sourceId) {
    document.querySelectorAll("[data-source-card]").forEach((card) => {
      card.classList.toggle("source-highlight", Boolean(sourceId) && card.dataset.sourceCard === sourceId);
    });
  }

  function loadBrowser() {
    const frameParams = new URLSearchParams();
    frameParams.set("config", new URL(frame.dataset.config, browserUrl).href);
    ["loc", "session", "tracks", "highlight"].forEach((key) => {
      const value = params.get(key);
      if (value) frameParams.set(key, value);
    });
    // Keep JBrowse's default session intact: it includes separate endpoint,
    // reference and, where available, +/− experimental signal tracks.
    frame.src = `${browserUrl.href}?${frameParams.toString()}`;
  }

  showSource(selectedSource());
  loadBrowser();

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
