"""Import every model here so `Base.metadata` knows the full schema."""
from .plots import Plot
from .calendar import CalendarEvent
from .management import ManagementEvent
from .observations import (
    ObservationSeries,
    PlotObservation,
    Scene,
    Baseline,
    Flag,
    Breakpoint,
)
from .soil import SoilSample, TreeCensus
from .sensors import SensorDevice, DataSource

__all__ = [
    "Plot",
    "CalendarEvent",
    "ManagementEvent",
    "ObservationSeries",
    "PlotObservation",
    "Scene",
    "Baseline",
    "Flag",
    "Breakpoint",
    "SoilSample",
    "TreeCensus",
    "SensorDevice",
    "DataSource",
]
