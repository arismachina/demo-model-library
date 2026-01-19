"""
Model Library - Battery Simulation Models

This package provides PyBaMM-based simulation functions for:
- DCIR (DC Internal Resistance)
- Power Capability
- Energy Capacity

All simulations use the unified SPMeT model with different experiment configurations.
"""

from .spmet import run_spmet

__all__ = ["run_spmet"]
__version__ = "0.1.0"
