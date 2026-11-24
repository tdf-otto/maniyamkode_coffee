/* Leaflet map: plot polygons coloured by the selected metric's status vs
   week-of-year baseline, latest composite as base imagery, time slider over
   monthly scenes, scene archive, compare mode. */
window.MapView = {
  map: null,
  plotLayer: null,
  boundaryLayer: null,
  baseOverlay: null,
  compareOverlay: null,
  plots: [],          // [{plot_id, plot_name, ...}]
  geojson: null,
  metric: "ndre",     // current metric switcher value
  scenes: [],         // s2 scenes sorted by date
  timeIndex: 0,
  layerByPlot: {},    // plot_id -> L.Polygon
  statusByPlot: {},   // plot_id -> {status, value, pctl, z, ts}
  compareMode: false,
  compareMap: null,

  METRICS: [
    { key: "ndre", source: "s2", label: "NDRE (early warning)" },
    { key: "evi", source: "s2", label: "EVI" },
    { key: "ndvi", source: "s2", label: "NDVI" },
    { key: "s1_vh", source: "s1", label: "S1-VH (monsoon)" },
    { key: "canopy_height_m", source: "canopy", label: "Canopy height" },
    { key: "elevation_m", source: "dem", label: "Elevation" },
    { key: "slope_deg", source: "dem", label: "Slope" },
    { key: "area", source: "plots", label: "Area" },
  ],

  STATUS_COLOR: { red: "#c0392b", amber: "#d99a26", green: "#3f8f4f" },

  async init() {
    const data = await API.plots(true);
    this.plots = data.plots;
    this.geojson = data.geojson;
    const bbox = data.bbox;

    this.map = L.map("map", { center: [(bbox.north + bbox.south) / 2, (bbox.east + bbox.west) / 2], zoom: 16 });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap contributors",
    }).addTo(this.map);

    this.boundaryLayer = L.geoJSON(this.geojson, {
      filter: (f) => f.properties.is_boundary,
      style: { color: "#8a5a2b", weight: 2, dashArray: "6 4", fillOpacity: 0.05 },
    }).addTo(this.map);

    this.plotLayer = L.geoJSON(this.geojson, {
      filter: (f) => !f.properties.is_boundary,
      style: (f) => this._style(f),
      onEachFeature: (f, layer) => {
        this.layerByPlot[f.properties.plot_id] = layer;
        layer.on("click", () => window.App.openPlot(f.properties.plot_id));
        layer.on("mouseover", () => this._tooltip(f.properties.plot_id, layer));
      },
    }).addTo(this.map);

    this.map.fitBounds(this.plotLayer.getBounds(), { padding: [20, 20] });

    // scenes for the time slider + archive
    const sc = await API.scenes("s2");
    this.scenes = sc.scenes.filter((s) => s.quicklook_path).sort((a, b) => a.date < b.date ? -1 : 1);
    const slider = document.getElementById("time-slider");
    slider.max = Math.max(0, this.scenes.length - 1);
    slider.value = slider.max;
    this.timeIndex = this.scenes.length - 1;
    slider.addEventListener("input", () => { this.timeIndex = +slider.value; this._onTimeChange(); });
    this._buildMetricSwitcher();
    this._onTimeChange();

    document.getElementById("toggle-boundaries").addEventListener("change", (e) => {
      if (e.target.checked) this.boundaryLayer.addTo(this.map);
      else this.map.removeLayer(this.boundaryLayer);
    });
    document.getElementById("btn-archive").addEventListener("click", () => this._toggleArchive());
    document.getElementById("btn-compare").addEventListener("click", () => this._toggleCompare());
    document.getElementById("btn-compare-close").addEventListener("click", () => this._toggleCompare(false));
    document.getElementById("btn-compare-apply").addEventListener("click", () => this._applyCompare());
  },

  _buildMetricSwitcher() {
    const div = document.getElementById("metric-switcher");
    div.innerHTML = "";
    this.METRICS.forEach((m) => {
      const b = document.createElement("button");
      b.textContent = m.label;
      b.classList.toggle("active", m.key === this.metric);
      b.addEventListener("click", () => {
        this.metric = m.key;
        this._buildMetricSwitcher();
        this._refreshLayer();
      });
      div.appendChild(b);
    });
  },

  _currentMetric() {
    return this.METRICS.find((m) => m.key === this.metric);
  },

  _style(feature) {
    const st = this.statusByPlot[feature.properties.plot_id];
    const color = st ? this.STATUS_COLOR[st.status] : "#888";
    return {
      color, weight: 2, fillColor: color, fillOpacity: st ? 0.45 : 0.15,
    };
  },

  async _refreshLayer() {
    const m = this._currentMetric();
    const date = this._currentDate();
    let layer;
    if (m.source === "plots") {
      // static: area — colour by quartile across plots
      const pts = this.plots.map((p) => ({ plot_id: p.plot_id, value: p.area_ha }));
      const vals = pts.map((p) => p.value).sort((a, b) => a - b);
      const q = (v) => { const i = vals.findIndex((x) => x >= v); return (i / vals.length) * 100; };
      this.statusByPlot = Object.fromEntries(pts.map((p) => [
        p.plot_id, { status: q(p.value) <= 25 ? "amber" : "green", value: p.value, pctl: q(p.value) }])),
    } else {
      layer = await API.maplayer(m.key, m.source, date);
      this.statusByPlot = Object.fromEntries(layer.points.map((p) => [p.plot_id, p]));
    }
    this.plotLayer.eachLayer((l) => {
      const f = l.feature;
      l.setStyle(this._style(f));
    });
    this._updateLegend();
  },

  _currentDate() {
    const s = this.scenes[this.timeIndex];
    return s ? s.date : null;
  },

  async _onTimeChange() {
    const s = this.scenes[this.timeIndex];
    document.getElementById("time-label").textContent = s ? s.date + (s.cloud_pct != null ? ` (cloud ${s.cloud_pct.toFixed(0)}%)` : "") : "";
    if (s && s.quicklook_path) {
      const url = `/processed/${s.quicklook_path}`;
      const bounds = this.plotLayer.getBounds();
      const pad = 0.004;
      const b = [[bounds.getSouth() - pad, bounds.getWest() - pad], [bounds.getNorth() + pad, bounds.getEast() + pad]];
      if (this.baseOverlay) this.map.removeLayer(this.baseOverlay);
      this.baseOverlay = L.imageOverlay(url, b, { opacity: 0.85 }).addTo(this.map);
      this._markActiveArchive(s.scene_id);
    }
    await this._refreshLayer();
  },

  _tooltip(plotId, layer) {
    const st = this.statusByPlot[plotId];
    const p = this.plots.find((x) => x.plot_id === plotId);
    if (!st || !p) return;
    const txt = `<b>${p.plot_name}</b> (${p.area_ha?.toFixed(2)} ha)<br>` +
      `${this.metric}: <b>${st.value}</b>` +
      (st.pctl != null ? ` — ${st.pctl.toFixed(0)}th pctl vs same week in past years` : "") +
      (st.z != null ? ` (z=${st.z.toFixed(1)})` : "") +
      `<br><span class="hint">${st.ts ? "as of " + st.ts.slice(0, 10) : ""}</span>`;
    layer.bindTooltip(txt, { sticky: true, className: "plot-tooltip" }).openTooltip();
  },

  _updateLegend() {
    let el = document.querySelector(".legend");
    if (!el) {
      el = L.control({ position: "bottomright" });
      el.onAdd = () => {
        const d = L.DomUtil.create("div", "legend");
        d.innerHTML = `<b>${this._currentMetric().label}</b><br>` +
          `<span style="color:#c0392b">■</span> below 5th pctl (red)<br>` +
          `<span style="color:#d99a26">■</span> 5–25th pctl (amber)<br>` +
          `<span style="color:#3f8f4f">■</span> normal (green)`;
        return d;
      };
      el.addTo(this.map);
    }
  },

  flyToPlot(plotId) {
    const layer = this.layerByPlot[plotId];
    if (layer) {
      this.map.flyTo(layer.getBounds().getCenter(), 18, { duration: 0.6 });
      layer.openTooltip ? layer.openTooltip() : null;
    }
  },

  async _toggleArchive(force) {
    const panel = document.getElementById("archive-panel");
    const show = force !== undefined ? force : panel.classList.contains("hidden");
    panel.classList.toggle("hidden", !show);
    if (show) {
      const grid = document.getElementById("archive-grid");
      grid.innerHTML = "";
      this.scenes.forEach((s, i) => {
        const d = document.createElement("div");
        d.className = "archive-item" + (i === this.timeIndex ? " active" : "");
        d.dataset.sceneId = s.scene_id;
        d.innerHTML = `<img src="/processed/${s.quicklook_path}" alt="${s.date}">` +
          `<div>${s.date}</div><div>cloud ${s.cloud_pct?.toFixed(0) ?? "?"}%</div>`;
        d.addEventListener("click", () => {
          document.getElementById("time-slider").value = i;
          this.timeIndex = i;
          this._onTimeChange();
        });
        grid.appendChild(d);
      });
    }
  },

  _markActiveArchive(sceneId) {
    document.querySelectorAll(".archive-item").forEach((el) =>
      el.classList.toggle("active", el.dataset.sceneId === sceneId));
  },

  _toggleCompare(force) {
    this.compareMode = force !== undefined ? force : !this.compareMode;
    document.getElementById("compare-bar").classList.toggle("hidden", !this.compareMode);
    if (this.compareMode) {
      const a = document.getElementById("compare-a"), b = document.getElementById("compare-b");
      const opts = this.scenes.map((s, i) => `<option value="${i}">${s.date}</option>`).join("");
      a.innerHTML = opts; b.innerHTML = opts;
      a.value = Math.max(0, this.scenes.length - 6);
      b.value = this.scenes.length - 1;
    }
  },

  _applyCompare() {
    // side-by-side quicklooks in the archive panel
    const i = +document.getElementById("compare-a").value;
    const j = +document.getElementById("compare-b").value;
    const panel = document.getElementById("archive-panel");
    panel.classList.remove("hidden");
    const grid = document.getElementById("archive-grid");
    grid.innerHTML = "";
    [this.scenes[i], this.scenes[j]].forEach((s) => {
      const d = document.createElement("div");
      d.className = "archive-item";
      d.innerHTML = `<img src="/processed/${s.quicklook_path}"><div><b>${s.date}</b> — cloud ${s.cloud_pct?.toFixed(0)}%</div>`;
      d.addEventListener("click", () => window.App.showLightbox(`/processed/${s.quicklook_path}`, s.date));
      grid.appendChild(d);
    });
  },
};
