#!/usr/bin/env python3
"""
Test if 1000 cycles can run in a single step with higher PyBaMM throughput limit
"""

import json
from pathlib import Path
from model_library.dfn_cycle_degradation import run_cycle_degradation

# Load cell design
cell_design_path = Path("cells/Tesla_Model3_Prismatic_160Ah_manifest.json")
with open(cell_design_path) as f:
    manifest = json.load(f)
    cell_design = manifest["cell_design"]

print("=" * 80)
print("TEST: Single-step 1000 cycle simulation")
print("=" * 80)
print(f"\nCell: Tesla Model 3 Prismatic 160 Ah")
print(f"Nominal capacity: {cell_design['nominal_capacity']['value']:.1f} Ah")

sim_config = {
    "num_cycles": 1000,
    "discharge_c_rate": 1.0,
    "charge_c_rate": 0.5,
    "ambient_temperature_C": 45,
    "initial_soc": 1.0,
    "soh_threshold": 80.0,
    "force_single_step": True,  # Force single-step, no multi-step delegation
}

print(f"\nSimulation config:")
print(f"  Cycles: {sim_config['num_cycles']}")
print(f"  Discharge C-rate: {sim_config['discharge_c_rate']}")
print(f"  Charge C-rate: {sim_config['charge_c_rate']}")
print(f"  Temperature: {sim_config['ambient_temperature_C']}°C")
print(f"  SoH threshold: {sim_config.get('soh_threshold', 'None')}")

print("\n" + "=" * 80)
result = run_cycle_degradation(cell_design, sim_config)
print("=" * 80)

if result["success"]:
    print("\n✓ Simulation succeeded!")
    summary = result["summary"]
    print(f"\n  Cycles completed: {summary['num_cycles_completed']}")
    print(f"  Initial capacity: {summary['initial_capacity_Ah']:.2f} Ah")
    print(f"  Final capacity: {summary['final_capacity_Ah']:.2f} Ah")
    print(f"  Capacity fade: {summary['capacity_fade_pct']:.2f}%")
    print(f"  Final SoH: {summary['final_soh_pct']:.2f}%")
else:
    print(f"\n✗ Simulation failed!")
    print(f"  Error: {result.get('error', 'Unknown')}")
