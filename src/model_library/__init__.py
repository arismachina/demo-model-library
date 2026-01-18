"""
Model Library - Battery Simulation Models

This package provides PyBaMM-based simulation functions for:
- DCIR (DC Internal Resistance)
- Power Capability
- Energy Capacity
"""

from .dcir_simulation import simulate_dcir
from .power_simulation import simulate_power
from .energy_simulation import simulate_energy

__all__ = ["simulate_dcir", "simulate_power", "simulate_energy"]
__version__ = "0.1.0"