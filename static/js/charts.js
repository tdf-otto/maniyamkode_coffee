/* Chart.js helpers: time-series with baseline band, season overlay. */
window.Charts = {
  _charts: [],
  destroyAll() { this._charts.forEach((c) => c.destroy()); this._charts = []; },

  timeseries(canvas, points, opts = {}) {
    const labels = points.map((p) => p.ts.slice(0, 10));
    const data = points.map((p) => p.value);
    const band = points.map((p) => (p.p05 != null && p.p95 != null) ? [p.p05, p.p95] : null);
    // build a floating band series [p05, p95]
    const bandData = points.map((p) => (p.p05 != null && p.p95 != null) ? [p.p05, p.p95] : null);
    const ch = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: opts.label || "value",
            data,
            borderColor: opts.color || "#4a6b3a",
            backgroundColor: (opts.color || "#4a6b3a") + "22",
            pointRadius: 3,
            tension: 0.25,
            spanGaps: true,
          },
          {
            label: "normal range (5–95 pctl, same week in past years)",
            data: bandData,
            borderColor: "transparent",
            backgroundColor: "#9a9a9a33",
            fill: "-1" === "-1" ? 1 : false, // fill between this and previous dataset
            pointRadius: 0,
            tension: 0.25,
          },
          {
            label: "median of past years",
            data: points.map((p) => p.median ?? null),
            borderColor: "#7a7264",
            borderDash: [5, 4],
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: true, labels: { boxWidth: 12, font: { size: 10 } } },
          tooltip: {
            callbacks: {
              label: (c) => {
                const p = points[c.dataIndex];
                let s = `${c.dataset.label}: ${p.value?.toFixed(3)}`;
                if (p.z != null) s += `  (z=${p.z.toFixed(1)}, pctl=${p.pctl?.toFixed(0)}%)`;
                return s;
              },
            },
          },
        },
        scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { title: { display: !!opts.unit, text: opts.unit || "" } } },
      },
    });
    this._charts.push(ch);
    return ch;
  },

  seasonOverlay(canvas, seriesPoints, currentSeason, opts = {}) {
    // seriesPoints: [{ts, value, season, day_of_season}]
    const bySeason = {};
    seriesPoints.forEach((p) => {
      (bySeason[p.season] = bySeason[p.season] || []).push(p);
    });
    const seasons = Object.keys(bySeason).sort();
    const palette = ["#4a6b3a", "#8a5a2b", "#7a7264", "#4a6b8a", "#8a4a6b"];
    const datasets = seasons.map((s, i) => ({
      label: s + (s === currentSeason ? " (current)" : ""),
      data: bySeason[s].map((p) => ({ x: p.day_of_season, y: p.value })),
      borderColor: s === currentSeason ? palette[0] : palette[i % palette.length],
      borderWidth: s === currentSeason ? 3 : 1,
      pointRadius: s === currentSeason ? 3 : 0,
      tension: 0.25,
    }));
    const ch = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        scales: {
          x: { type: "linear", title: { display: true, text: "day of coffee season (Oct 1 = 1)" }, min: 1, max: 365 },
          y: { title: { display: !!opts.unit, text: opts.unit || "" } },
        },
        plugins: { legend: { labels: { boxWidth: 12, font: { size: 10 } } } },
      },
    });
    this._charts.push(ch);
    return ch;
  },
};
