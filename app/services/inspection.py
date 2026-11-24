"""Inspection pack: one plot-season's complete dated history as CSV + PDF,
designed for organic-certification (NPOP) farm inspections.

Contents:
  - plot identity, area, conversion status
  - all management events in the season (harvest, applications with
    input_class + PHI, pest observations, field work, pruning, composting)
  - satellite-derived status summary for the season (mean NDVI/EVI/NDRE,
    flags raised, breakpoints detected)
  - placeholder rows for receipts (farmer attaches physical receipts)
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from reportlab.lib.styles import getSampleStyleSheet
from sqlalchemy import select

from .. import config
from ..db import SessionLocal
from ..db.models import Breakpoint, Flag, ManagementEvent, ObservationSeries, Plot, PlotObservation
from .organic import conversion_status
from .season import season_bounds, season_of


def _season_rows(plot_id: int, season: str):
    start, end = season_bounds(season)
    with SessionLocal() as s:
        evs = s.execute(
            select(ManagementEvent)
            .where(ManagementEvent.plot_id == plot_id,
                   ManagementEvent.event_date >= start.isoformat()[:10],
                   ManagementEvent.event_date <= end.isoformat()[:10])
            .order_by(ManagementEvent.event_date)
        ).scalars().all()
        return evs, start, end


def build_inspection_pack(plot_id: int, season: str | None = None,
                          out_dir: Path | None = None) -> tuple[Path, Path]:
    """Write <plot>_<season>.csv and .pdf into out_dir. Returns (csv_path, pdf_path)."""
    config.ensure_dirs()
    out_dir = out_dir or config.EXPORT_DIR / "inspection_packs"
    out_dir.mkdir(parents=True, exist_ok=True)
    season = season or season_of(date.today())
    with SessionLocal() as s:
        plot = s.get(Plot, plot_id)
        if plot is None:
            raise ValueError(f"unknown plot_id {plot_id}")
        name = plot.plot_name
    evs, start, end = _season_rows(plot_id, season)
    conv = conversion_status(plot_id)

    csv_path = out_dir / f"{name}_{season}_inspection.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["MANIYAMKODE (PUL) ESTATE — ORGANIC INSPECTION PACK (NPOP)"])
        w.writerow(["plot", name, "season (Indian coffee year, Oct-Sep)", season,
                    "period", f"{start}..{end}"])
        w.writerow(["conversion_status", conv["status"], conv.get("message", "")])
        w.writerow([])
        w.writerow(["date", "event_type", "product", "input_class", "pre_harvest_interval_days",
                    "quantity", "unit", "method", "actor", "notes"])
        for e in evs:
            meta = json.loads(e.meta_json) if e.meta_json else {}
            w.writerow([e.event_date, e.event_type, e.product or "", e.input_class or "",
                        e.pre_harvest_interval_days or "", e.quantity or "", e.unit or "",
                        e.method or "", e.actor or "", meta.get("notes", "")])
        w.writerow([])
        w.writerow(["RECEIPTS (attach):", "input", "invoice no.", "date", "supplier", "attached?"])
        for e in evs:
            if e.event_type == "application":
                w.writerow(["", e.product or "", "", "", "", "☐"])

    # --- PDF ---
    pdf_path = out_dir / f"{name}_{season}_inspection.pdf"
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                            leftMargin=1.5 * cm, rightMargin=1.5 * cm)
    story = [
        Paragraph(f"Inspection pack — {name} ({season})", styles["Title"]),
        Paragraph(f"Maniyamkode (PUL) estate, Wayanad, Kerala — Indian coffee year "
                  f"{start} to {end}", styles["Normal"]),
        Paragraph(f"Conversion status: {conv['status']} — {conv.get('message', '')}",
                  styles["Normal"]),
        Spacer(1, 0.4 * cm),
        Paragraph("Management records", styles["Heading2"]),
    ]
    data = [["Date", "Type", "Product", "Input class", "PHI (d)", "Qty", "Unit", "Actor"]]
    for e in evs:
        data.append([e.event_date, e.event_type, e.product or "", e.input_class or "",
                     str(e.pre_harvest_interval_days or ""), str(e.quantity or ""),
                     e.unit or "", e.actor or ""])
    if len(data) > 1:
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe8d8")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
    else:
        story.append(Paragraph("No management records this season.", styles["Normal"]))

    # satellite-derived status summary
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Satellite-derived status (Sentinel-2 / Sentinel-1, local processing)",
                           styles["Heading2"]))
    with SessionLocal() as s:
        flags = s.execute(select(Flag).where(Flag.plot_id == plot_id)).scalars().all()
        bps = s.execute(select(Breakpoint).where(Breakpoint.plot_id == plot_id)).scalars().all()
        ser = {r.variable: r.series_id for r in s.execute(select(ObservationSeries)).scalars()}
        summary = []
        for var in ("ndvi", "evi", "ndre"):
            if var in ser:
                rows = s.execute(
                    select(PlotObservation).where(
                        PlotObservation.series_id == ser[var], PlotObservation.plot_id == plot_id,
                        PlotObservation.ts >= start.isoformat()[:10],
                        PlotObservation.ts <= (end.isoformat()[:10] + "T23:59:59"),
                        PlotObservation.valid == 1)
                ).scalars().all()
                if rows:
                    vals = [r.value for r in rows if r.value is not None]
                    if vals:
                        summary.append([var, f"{min(vals):.3f}", f"{sum(vals)/len(vals):.3f}",
                                        f"{max(vals):.3f}", str(len(vals))])
    if summary:
        t2 = Table([["variable", "min", "mean", "max", "n scenes"]] + summary)
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfe8d8")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(t2)
    if flags:
        story.append(Paragraph("Flags raised", styles["Heading3"]))
        for f in flags:
            story.append(Paragraph(f"• {f.scene_date or ''} [{f.severity}] {f.message}",
                                   styles["Normal"]))
    if bps:
        story.append(Paragraph("Detected change-points", styles["Heading3"]))
        for b in bps:
            story.append(Paragraph(f"• {b.break_date}: disturbance suspected "
                                   f"(magnitude {b.magnitude:.2f}, {b.method})", styles["Normal"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Receipts: attach purchase invoices for all inputs listed above.",
                           styles["Italic"]))
    doc.build(story)
    return csv_path, pdf_path
