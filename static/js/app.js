/* App wiring: top strip, attention list, drawer, export, lightbox, i18n. */
window.App = {
  async init() {
    window.applyI18n();
    document.getElementById("btn-lang").addEventListener("click", () => {
      window.LANG = window.LANG === "en" ? "ml" : "en";
      document.getElementById("btn-lang").textContent = window.LANG.toUpperCase();
      window.applyI18n();
    });
    document.getElementById("btn-export").addEventListener("click", () => {
      window.location = "/api/export";
    });
    document.getElementById("lightbox-close").addEventListener("click", () =>
      document.getElementById("lightbox").classList.add("hidden"));

    await this._loadHome();
    await window.MapView.init();
  },

  async _loadHome() {
    const h = await API.home();
    // phenostage chip
    const chip = document.getElementById("phenostage-chip");
    if (h.phenostage) {
      chip.textContent = `${t("phenostage_label")}: ${h.phenostage.phenostage}`;
      chip.title = h.phenostage.typical_activities || "";
    }
    const mon = document.getElementById("monsoon-chip");
    mon.classList.toggle("hidden", !h.monsoon);
    if (h.monsoon) mon.textContent = t("monsoon_on");
    // source freshness
    document.getElementById("source-freshness").innerHTML = h.sources.map((s) =>
      `<span class="src" title="${s.description || ""} — last run ${s.last_run || "never"}">
        <span class="dot ${s.status}"></span><b>${s.source_key}</b> ${s.status === "ok" ? (s.last_run || "").slice(0, 10) : s.status}</span>`).join("");
    // ranked flag list
    const list = document.getElementById("flag-list");
    if (!h.flags.length) {
      list.innerHTML = `<div class="flag-empty">✓ ${t("all_clear")}</div>`;
      return;
    }
    list.innerHTML = "";
    for (const f of h.flags) {
      const card = document.createElement("div");
      card.className = `flag-card ${f.severity}`;
      card.innerHTML = `
        <div class="row1"><span class="plot">${f.plot_name}</span>
          <span class="chip ${f.severity}">${f.severity.toUpperCase()}</span></div>
        <div class="msg">${f.message}</div>
        <div class="meta"><canvas class="spark" width="120" height="28"></canvas>
          <span>${f.variable} · ${f.scene_date ? f.scene_date.slice(0, 10) : ""}</span></div>`;
      card.addEventListener("click", () => this.openPlot(f.plot_id));
      list.appendChild(card);
      // sparkline of that plot+series
      API.observations(f.plot_id, f.variable, f.source || "s2").then((r) => {
        Sparkline.draw(card.querySelector("canvas"), r.points.slice(-24), {
          color: f.severity === "red" ? "#c0392b" : f.severity === "amber" ? "#d99a26" : "#3f8f4f",
          dot: f.severity === "red" ? "#c0392b" : f.severity === "amber" ? "#d99a26" : "#3f8f4f",
        });
      }).catch(() => {});
    }
  },

  openPlot(plotId) {
    window.MapView.flyToPlot(plotId);
    window.Drawer.open(plotId);
  },

  showLightbox(src, caption) {
    document.getElementById("lightbox-img").src = src;
    document.getElementById("lightbox").classList.remove("hidden");
  },
};

window.addEventListener("DOMContentLoaded", () => window.App.init().catch((e) => {
  document.getElementById("flag-list").innerHTML = `<p class="hint">Error: ${e.message}</p>`;
  console.error(e);
}));
