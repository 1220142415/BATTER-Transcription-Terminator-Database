(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const number = (value) => Number(value).toLocaleString("en");
  const SVG = "http://www.w3.org/2000/svg";
  const colors = ["#dddaf4", "#bcb7e6", "#948bd3", "#7369bf", "#51469e"];
  const ranges = ["7", "30", "90", "365", "0"];
  let activeRequest;
  let mapData;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function svgNode(tag, attributes = {}, title) {
    const element = document.createElementNS(SVG, tag);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
    if (title !== undefined) {
      const label = document.createElementNS(SVG, "title");
      label.textContent = title;
      element.append(label);
    }
    return element;
  }

  function table(id, rows, cells) {
    $(id).replaceChildren(...rows.map((entry) => {
      const row = node("tr");
      cells(entry).forEach((value, index) => {
        const cell = node(index === 0 ? "th" : "td");
        if (index === 0) cell.scope = "row";
        cell.append(value instanceof Node ? value : document.createTextNode(String(value)));
        row.append(cell);
      });
      return row;
    }));
  }

  function drawMap(report, data) {
    const measured = new Map(report.countries.map((row) => [row.code, row]));
    const max = Math.max(0, ...report.countries.filter((row) => row.code !== "XX").map((row) => row.views));
    const svg = svgNode("svg", { viewBox: `0 0 ${data.width} ${data.height}`, role: "img", "aria-label": "Page views by country or region. Counts are listed in the table below." });
    svg.append(svgNode("path", { d: data.sphere, class: "usage-map-sphere" }));
    for (const country of data.countries) {
      const row = measured.get(country.code);
      const index = row?.views > 0 ? Math.min(4, Math.floor(Math.log1p(row.views) / Math.log1p(max) * 5)) : -1;
      const name = row?.name || ({ HK: "Hong Kong, China", MO: "Macao, China", TW: "Taiwan, China" }[country.code]) || country.name;
      svg.append(svgNode("path", { d: country.d, fill: index < 0 ? "#ececf3" : colors[index], class: "usage-map-country" }, `${name}: ${number(row?.views || 0)} page views`));
    }
    $("usage-map").replaceChildren(svg);
    $("usage-map-max").textContent = `${number(max)} views`;
  }

  function drawTrend(report) {
    const max = Math.max(1, ...report.daily.map((row) => row.views));
    const svg = svgNode("svg", { viewBox: `0 0 ${report.daily.length * 4} 100`, preserveAspectRatio: "none", role: "img", "aria-label": `Daily page views, ${report.startDay} to ${report.endDay}. Highest daily count: ${number(max)}.` });
    report.daily.forEach((row, index) => {
      const height = row.views / max * 96;
      svg.append(svgNode("rect", { x: index * 4, y: 100 - height, width: 3, height, fill: "#7369bf" }, `${row.day}: ${number(row.views)} page views`));
    });
    $("usage-trend").replaceChildren(svg);
    $("usage-start").textContent = report.startDay;
    $("usage-end").textContent = report.endDay;
  }

  function render(report) {
    $("usage-views").textContent = number(report.totals.views);
    $("usage-countries").textContent = number(report.totals.countries);
    $("usage-active").textContent = number(report.totals.activeDays);
    table("usage-country-rows", report.countries, (row) => {
      const share = node("span", undefined, "usage-share");
      const track = node("span", undefined, "usage-share-track");
      const bar = node("i");
      bar.style.width = `${row.share * 100}%`;
      track.append(bar);
      track.setAttribute("aria-hidden", "true");
      share.append(track, `${(row.share * 100).toFixed(1)}%`);
      return [row.name, number(row.views), share];
    });
    table("usage-city-rows", report.cities, (row) => {
      const name = node("span", row.city);
      name.append(node("small", [row.region === row.city ? "" : row.region, row.countryName].filter(Boolean).join(", ")));
      return [name, number(row.views)];
    });
    $("usage-no-cities").hidden = report.cities.length > 0;
    table("usage-path-rows", report.paths, (row) => {
      const label = row.path === "/" ? "Home" : row.path === "/genomes" ? "Genomes" : row.path === "/methodology" ? "Data notes" : row.path;
      const link = node("a", label);
      // Only link known page paths, never arbitrary values returned by a database.
      if (["/", "/genomes", "/methodology"].includes(row.path) || /^\/genomes\/GCF_[0-9]+\.[0-9]+$/.test(row.path)) {
        link.href = row.path === "/" ? "index.html" : `${row.path.slice(1)}.html`;
      }
      return [link, number(row.views)];
    });
    drawTrend(report);
    $("usage-period").textContent = `UTC: ${report.startDay} to ${report.endDay}.${report.firstRecordedDay ? ` First recorded: ${report.firstRecordedDay}.` : ""} Cities: top 50. Pages: top 30.`;
    $("usage-status").textContent = report.totals.views ? "" : "No page views in this period. Counting starts after deployment.";
    $("usage-report").hidden = false;
  }

  async function load(days) {
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    $("usage-status").textContent = "Loading usage…";
    $("usage-report").hidden = true;
    try {
      const response = await fetch(`/api/usage?days=${days}`, { signal: controller.signal, credentials: "omit" });
      if (!response.ok) throw new Error("Usage unavailable");
      const report = await response.json();
      if (controller.signal.aborted) return;
      render(report);
      try {
        if (!mapData) {
          const mapResponse = await fetch("assets/usage-world-map.json", { signal: controller.signal });
          if (!mapResponse.ok) throw new Error("Map unavailable");
          mapData = await mapResponse.json();
        }
        if (!controller.signal.aborted) drawMap(report, mapData);
      } catch (error) {
        if (error.name !== "AbortError") $("usage-map").replaceChildren(node("p", "Map unavailable. Country counts are listed below."));
      }
    } catch (error) {
      if (error.name !== "AbortError") $("usage-status").textContent = "Usage is unavailable. Select Apply to retry.";
    }
  }

  const requested = new URLSearchParams(location.search).get("days");
  $("usage-days").value = ranges.includes(requested) ? requested : "30";
  document.querySelector(".usage-range").addEventListener("submit", (event) => {
    event.preventDefault();
    const days = $("usage-days").value;
    const url = new URL(location.href);
    url.searchParams.set("days", days);
    history.replaceState(null, "", url);
    load(days);
  });
  $("usage-days").addEventListener("change", () => document.querySelector(".usage-range").requestSubmit());
  load($("usage-days").value);
})();
