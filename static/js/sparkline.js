/* Tiny canvas sparklines for flag rows and chips. */
window.Sparkline = {
  draw(canvas, points, opts = {}) {
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || 120, h = canvas.clientHeight || 28;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    if (!points || points.length < 2) return;
    const vals = points.map((p) => p.value).filter((v) => v !== null && v !== undefined);
    if (!vals.length) return;
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const span = hi - lo || 1;
    // baseline band (p05-p95) if present on points
    const p05 = points.map((p) => p.p05).find((v) => v != null);
    const p95 = points.map((p) => p.p95).find((v) => v != null);
    if (p05 != null && p95 != null) {
      const y1 = h - ((p95 - lo) / span) * h, y2 = h - ((p05 - lo) / span) * h;
      ctx.fillStyle = "#8a8a8a18";
      ctx.fillRect(0, y1, w, Math.max(1, y2 - y1));
    }
    ctx.strokeStyle = opts.color || "#4a6b3a";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    points.forEach((p, i) => {
      if (p.value == null) return;
      const x = (i / (points.length - 1)) * (w - 4) + 2;
      const y = h - 3 - ((p.value - lo) / span) * (h - 6);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    // last point dot, coloured by status
    const last = points[points.length - 1];
    if (last && last.value != null) {
      const x = w - 2, y = h - 3 - ((last.value - lo) / span) * (h - 6);
      ctx.fillStyle = opts.dot || "#4a6b3a";
      ctx.beginPath(); ctx.arc(x, y, 2.6, 0, 7); ctx.fill();
    }
  },
};
