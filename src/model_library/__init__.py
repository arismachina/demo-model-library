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
from .eis import run_eis, nyquist_plot, bode_plot

__all__ = ["run_spmet", "run_eis", "nyquist_plot", "bode_plot"]
__version__ = "0.1.0"
