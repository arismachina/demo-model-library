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
from .cell_capacity import get_cell_capacity
from .spmet_dcir import run_spmet_dcir
from .spmet_energy import run_spmet_energy
from .spmet_power import run_spmet_power
from .spmet_fastcharge import run_spmet_fastcharge
from .spmet_drive import run_spmet_drivecycle
from .spmet_bess import run_spmet_dutycycle
from .dfn_drive_degradation import run_drive_cycle_with_degradation
from .dfn_calendar_degradation import run_calendar_degradation
from .dfn_cycle_degradation import run_cycle_degradation
from .eis import run_eis, nyquist_plot, bode_plot

__all__ = [
    "run_spmet",
    "get_cell_capacity",
    "run_spmet_dcir",
    "run_spmet_energy",
    "run_spmet_power",
    "run_spmet_fastcharge",
    "run_spmet_drivecycle",
    "run_spmet_dutycycle",
    "run_drive_cycle_with_degradation",
    "run_calendar_degradation",
    "run_cycle_degradation",
    "run_eis",
    "nyquist_plot",
    "bode_plot",
]
__version__ = "0.1.0"
