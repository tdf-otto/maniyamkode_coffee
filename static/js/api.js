/* Thin fetch wrapper for the FastAPI backend. */
window.API = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`);
    return r.json();
  },
  async del(path) {
    const r = await fetch(path, { method: "DELETE" });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  },

  home: () => API.get("/api/home"),
  plots: (withBoundaries) => API.get(`/api/plots?include_boundaries=${withBoundaries ? 1 : 0}`),
  plot: (id) => API.get(`/api/plots/${id}`),
  observations: (plotId, series, source, frm, to) =>
    API.get(`/api/observations?plot_id=${plotId}&series=${series}&source=${source}${frm ? "&frm=" + frm : ""}${to ? "&to=" + to : ""}`),
  season: (plotId, season) => API.get(`/api/plots/${plotId}/season${season ? "?season=" + season : ""}`),
  soil: (plotId) => API.get(`/api/plots/${plotId}/soil`),
  records: (plotId) => API.get(`/api/plots/${plotId}/records`),
  addRecord: (plotId, rec) => API.post(`/api/plots/${plotId}/records`, rec),
  deleteRecord: (id) => API.del(`/api/records/${id}`),
  scenes: (source) => API.get(`/api/scenes${source ? "?source=" + source : ""}`),
  series: () => API.get("/api/series"),
  calendar: () => API.get("/api/calendar"),
  setConversion: (plotId, date) => API.put(`/api/plots/${plotId}/conversion`, { start_date: date }),
  inspectionPack: (plotId, season) =>
    API.post(`/api/plots/${plotId}/inspection-pack${season ? "?season=" + season : ""}`),
};
