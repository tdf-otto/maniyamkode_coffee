/* Plot drawer: Overview / Season / Imagery / Records / Soil & census tabs. */
window.Drawer = {
  plotId: null,
  data: null,

  async open(plotId) {
    this.plotId = plotId;
    document.getElementById("drawer").classList.remove("hidden");
    document.querySelectorAll("#drawer-tabs button").forEach((b) =>
      b.classList.toggle("active", b.dataset.tab === "overview"));
    document.querySelectorAll(".tab-pane").forEach((p) => p.classList.add("hidden"));
    document.getElementById("tab-overview").classList.remove("hidden");
    this.data = await API.plot(plotId);
    document.getElementById("drawer-title").textContent =
      `${this.data.plot_name} — ${this.data.area_ha?.toFixed(2)} ha`;
    this._renderOverview();
    this._loadSeason();
    this._loadImagery();
    this._loadRecords();
    this._loadSoil();

    document.querySelectorAll("#drawer-tabs button").forEach((b) =>
      (b.onclick = () => {
        document.querySelectorAll("#drawer-tabs button").forEach((x) => x.classList.toggle("active", x === b));
        document.querySelectorAll(".tab-pane").forEach((p) => p.classList.add("hidden"));
        document.getElementById("tab-" + b.dataset.tab).classList.remove("hidden");
      }));
    document.getElementById("drawer-close").onclick = () =>
      document.getElementById("drawer").classList.add("hidden");
  },

  _chip(s) {
    return `<span class="chip ${s.status}" title="value ${s.value} ${s.unit || ""} as of ${s.ts?.slice(0, 10)} — ${s.pctl?.toFixed(0)}th percentile vs same week in past years (z=${s.z?.toFixed(1)})">${s.variable}: ${s.value} ${s.unit || ""} · ${s.pctl != null ? s.pctl.toFixed(0) + "pctl" : "n/a"}</span>`;
  },

  _renderOverview() {
    const d = this.data;
    const conv = d.conversion;
    const convTxt = conv.status === "not_in_conversion" ? "Not in conversion" :
      conv.status === "in_conversion" ? `In conversion (${conv.days_remaining} days left)` :
      conv.status === "certified_eligible" ? "Conversion complete" : conv.status;
    document.getElementById("tab-overview").innerHTML = `
      <dl class="kv">
        <dt>Estate</dt><dd>${d.estate}</dd>
        <dt>${t("area")}</dt><dd>${d.area_ha?.toFixed(3)} ha (UTM 43N)</dd>
        <dt>${t("conversion")}</dt>
        <dd><span class="chip ${conv.status === "in_conversion" ? "amber" : "green"}">${convTxt}</span>
            <div class="hint">${conv.message || ""}</div>
            <button id="btn-set-conv" class="primary" style="margin-top:4px">${t("set_conversion")}</button>
            <input type="date" id="conv-date" style="margin-left:6px"></dd>
      </dl>
      <h3>${t("current_status")}</h3>
      <div class="chip-row">${d.chips.map((c) => this._chip(c)).join("") || '<span class="hint">no data yet</span>'}</div>
      <p class="hint">Chips show each series' latest value and its percentile versus the same week of the year in past seasons. Hover for the raw index and z-score.</p>`;
    document.getElementById("btn-set-conv").onclick = async () => {
      const v = document.getElementById("conv-date").value || null;
      await API.setConversion(this.plotId, v);
      this.data = await API.plot(this.plotId);
      this._renderOverview();
    };
  },

  async _loadSeason() {
    const el = document.getElementById("tab-season");
    const seasonData = await API.season(this.plotId);
    const seasons = [...new Set(Object.values(seasonData.series).flat().map((p) => p.season))].sort().reverse();
    const current = seasonData.season;
    el.innerHTML = `
      <label class="hint">${t("season_selector")}
        <select id="season-select">${seasons.map((s) => `<option ${s === current ? "selected" : ""}>${s}</option>`).join("")}</select>
      </label>
      <p class="chart-hint">${t("what_am_i_looking_at_season")}</p>
      <h4>NDRE (early-warning)</h4><div class="chart-box"><canvas id="ch-ndre-season"></canvas></div>
      <h4>EVI (canopy structure)</h4><div class="chart-box"><canvas id="ch-evi-season"></canvas></div>
      <h4>S1-VH (monsoon layer)</h4><div class="chart-box"><canvas id="ch-s1-season"></canvas></div>
      <h4>${t("what_am_i_looking_at_ts").split(".")[0]}.</h4>
      <p class="chart-hint">${t("what_am_i_looking_at_ts")}</p>
      <h4>NDRE full history</h4><div class="chart-box"><canvas id="ch-ndre-ts"></canvas></div>
      <h4>${t("breakpoints")}</h4>
      <ul>${seasonData.breakpoints.map((b) => `<li>${b.break_date} — ${b.variable}, magnitude ${b.magnitude?.toFixed(2)} (${b.method})</li>`).join("") || "<li>none detected</li>"}</ul>
      <h4>${t("events_overlay")}</h4>
      <ul>${seasonData.events.map((e) => `<li>${e.date} — ${e.type}${e.product ? " (" + e.product + (e.input_class ? ", " + e.input_class : "") + ")" : ""}</li>`).join("") || "<li>none yet</li>"}</ul>`;
    const draw = (season) => {
      Charts.destroyAll();
      const sel = season || document.getElementById("season-select").value;
      const pts = (v) => (seasonData.series[v] || []).filter((p) => p.season === sel || true);
      Charts.seasonOverlay(document.getElementById("ch-ndre-season"), pts("ndre"), sel, { unit: "-" });
      Charts.seasonOverlay(document.getElementById("ch-evi-season"), pts("evi"), sel, { unit: "-" });
      Charts.seasonOverlay(document.getElementById("ch-s1-season"), pts("s1_vh"), sel, { unit: "dB" });
      // full history with baseline band
      API.observations(this.plotId, "ndre", "s2").then((r) =>
        Charts.timeseries(document.getElementById("ch-ndre-ts"), r.points, { label: "NDRE", color: "#8a5a2b" }));
    };
    document.getElementById("season-select").addEventListener("change", (e) => draw(e.target.value));
    draw(current);
  },

  async _loadImagery() {
    const el = document.getElementById("tab-imagery");
    const sc = await API.scenes("s2");
    const scenes = sc.scenes.filter((s) => s.quicklook_path).sort((a, b) => a.date < b.date ? 1 : -1).slice(-24);
    el.innerHTML = `<p class="chart-hint">${t("imagery_hint")}</p>
      <div class="gallery">${scenes.map((s) => `
        <figure data-src="/processed/${s.quicklook_path}">
          <img src="/processed/${s.quicklook_path}" loading="lazy" alt="${s.date}">
          <figcaption>${s.date} · NDRE quicklook · cloud ${s.cloud_pct?.toFixed(0) ?? "?"}%</figcaption>
        </figure>`).join("")}</div>`;
    el.querySelectorAll("figure").forEach((f) =>
      (f.onclick = () => window.App.showLightbox(f.dataset.src, f.querySelector("figcaption").textContent)));
  },

  async _loadRecords() {
    const el = document.getElementById("tab-records");
    const recs = await API.records(this.plotId);
    const rows = recs.records.map((r) => {
      const bad = r.compliance && !r.compliance.ok;
      return `<tr class="${bad ? "nonconforming" : ""}">
        <td>${r.event_date}</td><td>${r.event_type}</td>
        <td>${r.product || ""}</td>
        <td>${r.input_class || ""}</td>
        <td>${r.pre_harvest_interval_days ?? ""}</td>
        <td>${r.quantity ?? ""} ${r.unit || ""}</td>
        <td>${r.actor || ""}</td>
        <td>${bad ? `<span class="warn">⚠ ${r.compliance.reason}</span>` : ""}
            <button class="del" data-id="${r.id}">✕</button></td>
      </tr>`;
    }).join("");
    el.innerHTML = `
      <p class="chart-hint">${t("records_hint")}</p>
      <table class="records">
        <thead><tr><th>date</th><th>type</th><th>product</th><th>input class</th><th>PHI d</th><th>qty</th><th>actor</th><th></th></tr></thead>
        <tbody>${rows || `<tr><td colspan="8" class="hint">${t("no_records")}</td></tr>`}</tbody>
      </table>
      <h4>${t("add_record")}</h4>
      <form class="record-form" id="rec-form">
        <label>date<input type="date" name="event_date" required></label>
        <label>type<select name="event_type">
          <option>harvest</option><option>application</option><option>pest_observation</option>
          <option>field_work</option><option>pruning</option><option>composting</option></select></label>
        <label>product<input name="product"></label>
        <label>input class<select name="input_class"><option value="">—</option>
          <option>organic_allowed</option><option>restricted</option><option>prohibited</option></select></label>
        <label>PHI (days)<input name="pre_harvest_interval_days" type="number"></label>
        <label>quantity<input name="quantity" type="number" step="any"></label>
        <label>unit<input name="unit" placeholder="kg / L / acres"></label>
        <label>actor<input name="actor"></label>
        <label class="full">method<input name="method"></label>
        <label class="full"><button class="primary" type="submit">${t("add_record")}</button></label>
      </form>
      <h4>${t("inspection_pack")}</h4>
      <p class="chart-hint">${t("inspection_pack_hint")}</p>
      <button id="btn-pack" class="primary">${t("inspection_pack")} — CSV + PDF</button>
      <div id="pack-result"></div>`;
    el.querySelectorAll("button.del").forEach((b) => (b.onclick = async () => {
      await API.deleteRecord(+b.dataset.id); this._loadRecords();
    }));
    document.getElementById("rec-form").onsubmit = async (e) => {
      e.preventDefault();
      const f = new FormData(e.target);
      const rec = Object.fromEntries(f.entries());
      if (rec.pre_harvest_interval_days) rec.pre_harvest_interval_days = +rec.pre_harvest_interval_days;
      if (rec.quantity) rec.quantity = +rec.quantity;
      if (!rec.input_class) rec.input_class = null;
      await API.addRecord(this.plotId, rec);
      this._loadRecords();
    };
    document.getElementById("btn-pack").onclick = async () => {
      const r = await API.inspectionPack(this.plotId);
      document.getElementById("pack-result").innerHTML =
        `<a href="${r.csv_url}">CSV</a> · <a href="${r.pdf_url}">PDF</a>`;
    };
  },

  async _loadSoil() {
    const el = document.getElementById("tab-soil");
    const d = await API.soil(this.plotId);
    const params = Object.entries(d.soil);
    el.innerHTML = `
      <h4>Soil samples</h4>
      ${params.length ? params.map(([param, rows]) => `
        <h5>${param}</h5>
        <table class="records"><thead><tr><th>date</th><th>value</th><th>unit</th><th>depth cm</th><th>lab</th></tr></thead>
        <tbody>${rows.map((r) => `<tr><td>${r.sample_date}</td><td>${r.value}</td><td>${r.unit || ""}</td><td>${r.depth_cm ?? ""}</td><td>${r.lab || ""}</td></tr>`).join("")}</tbody></table>`).join("")
      : `<p class="hint">${t("no_soil")}</p>`}
      <h4>Tree census</h4>
      ${d.census.length ? `<table class="records"><thead><tr><th>date</th><th>trees</th><th>coffee/shade</th><th>source</th></tr></thead>
        <tbody>${d.census.map((c) => `<tr><td>${c.census_date}</td><td>${c.tree_count ?? ""}</td><td>${c.coffee_shade_split || ""}</td><td>${c.source || ""}</td></tr>`).join("")}</tbody></table>`
      : `<p class="hint">${t("no_soil")}</p>`}`;
  },
};
