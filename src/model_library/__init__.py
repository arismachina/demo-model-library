"""
Model Library - Battery Simulation Models

This package provides PyBaMM-based simulation functions for:
- DCIR (DC Internal Resistance)
- Power Capability
- Energy Capacity
- EIS (Electrochemical Impedance Spectroscopy)

All simulations use the unified SPMeT model with different experiment configurations,
except EIS which uses PyBaMM-EIS for frequency-domain analysis.
"""

from .spmet import run_spmet
from .spmet_drive import run_drive_cycle, print_drive_cycle_report
from .dfn_drive_degradation import (
    run_drive_cycle_with_degradation,
    print_drive_cycle_degradation_report,
    print_multi_cycle_summary,
)
from .dfn_calendar_degradation import run_calendar_degradation
from .dfn_cycle_degradation import (
    run_cycle_degradation,
    run_cycle_degradation_multistep,
)
from .eis import run_eis, nyquist_plot, bode_plot
from .cell_capacity import get_cell_capacity
from .spmet_dcir import simulate_dcir

__all__ = [
    "run_spmet",
    "run_drive_cycle",
    "print_drive_cycle_report",
    "run_drive_cycle_with_degradation",
    "print_drive_cycle_degradation_report",
    "print_multi_cycle_summary",
    "run_calendar_degradation",
    "run_cycle_degradation",
    "run_cycle_degradation_multistep",
    "run_eis",
    "nyquist_plot",
    "bode_plot",
    "get_cell_capacity",
    "simulate_dcir",
]
__version__ = "0.1.0"
