/* i18n string table. English now; Malayalam labels can be added under "ml"
   and switched with the EN/ML button (data-i18n attributes are translated). */
window.STRINGS = {
  en: {
    estate_name: "Maniyamkode (PUL), Wayanad",
    attention_title: "What needs attention",
    attention_hint: "Ranked worst-first. Click a row to fly to the plot and open its drawer.",
    export_all: "Export everything (.zip)",
    compare: "Compare",
    compare_hint: "Two-date compare (before/after an intervention):",
    apply: "Apply",
    scenes: "Scene archive",
    scene_archive: "Scene archive — monthly composites (click to set as base layer)",
    tab_overview: "Overview",
    tab_season: "Season",
    tab_imagery: "Imagery",
    tab_records: "Records",
    tab_soil: "Soil & census",
    all_clear: "All plots are within their historical range for this week.",
    monsoon_on: "Monsoon — optical paused, Sentinel-1 layer active",
    phenostage_label: "Phenostage",
    freshness: "freshness",
    what_am_i_looking_at_ts: "Each dot is one satellite acquisition. The grey band is the normal range for that week of the year in past seasons; dots below it need attention.",
    what_am_i_looking_at_season: "Current coffee-year trajectory (thick line) over previous seasons (thin lines), aligned by day of season (Oct 1 = day 1).",
    records_hint: "Harvest, applications, pest observations, field work. Applications are checked against the plot's organic-conversion status.",
    inspection_pack: "Inspection pack (NPOP)",
    inspection_pack_hint: "Exports this plot-season's complete dated history as CSV + PDF for organic-certification inspection.",
    add_record: "Add record",
    no_records: "No records yet.",
    no_soil: "No soil samples or tree census yet — these tables auto-populate when the soil/tree ingest runs.",
    conversion: "Organic conversion",
    set_conversion: "Set conversion start date",
    area: "Area", elevation: "Elevation", slope: "Slope", canopy: "Canopy height",
    current_status: "Current status vs same week in past years",
    breakpoints: "Detected change-points",
    events_overlay: "Management events",
    season_selector: "Season (Indian coffee year, Oct–Sep)",
    imagery_hint: "Per-plot quicklooks by date. Click to enlarge.",
    metric: "Map metric",
  },
  ml: {
    // Malayalam labels — to be filled in; falls back to English per key.
  },
};
window.LANG = "en";
window.t = function (key) {
  return (window.STRINGS[window.LANG] && window.STRINGS[window.LANG][key]) ||
         window.STRINGS.en[key] || key;
};
window.applyI18n = function () {
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = window.t(el.dataset.i18n); });
};
