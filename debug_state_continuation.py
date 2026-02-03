#!/usr/bin/env python3
"""
Debug script to understand solution.cycles behavior with set_initial_conditions_from()
"""

import pybamm
import numpy as np
from model_library.dfn_cycle_degradation import (
    build_dfn_cycle_degradation_params,
    build_dfn_cycle_model_options,
)

# Test setup
pybamm.settings.max_y_value = 500000.0

cell_design = {
    "nominal_capacity": {"value": 161.1},
    "energy": {"value": 700},
    "voltage": {"min": 2.5, "max": 4.2, "nominal": 3.65},
}

sim_config = {
    "discharge_c_rate": 1.0,
    "charge_c_rate": 0.5,
    "ambient_temperature_C": 45,
    "initial_soc": 1.0,
}

# Build model and parameters
model_options = build_dfn_cycle_model_options()
params = build_dfn_cycle_degradation_params(cell_design, sim_config)

print("=" * 80)
print("TEST 1: Single step - check solution.cycles")
print("=" * 80)

# Create first model
model1 = pybamm.lithium_ion.DFN(options=model_options)

# Create experiment for 2 cycles
experiment1 = pybamm.Experiment(
    [
        "Discharge at 161.1 A until 2.5 V",
        "Charge at 80.55 A until 4.2 V",
        "Discharge at 161.1 A until 2.5 V",
        "Charge at 80.55 A until 4.2 V",
    ],
    period="1 minute",
)

sim1 = pybamm.Simulation(
    model1,
    experiment=experiment1,
    parameter_values=params,
    var_pts={"x_n": 10, "x_s": 10, "x_p": 10, "r_n": 30, "r_p": 30},
)

solver = pybamm.IDAKLUSolver(atol=1e-4, rtol=1e-4)
solution1 = sim1.solve(initial_soc=1.0, solver=solver)

print(f"\nSolution 1 (first 2 cycles):")
print(f"  solution.cycles exists: {hasattr(solution1, 'cycles')}")
if hasattr(solution1, "cycles"):
    print(f"  len(solution.cycles): {len(solution1.cycles)}")
print(
    f"  solution.t (time): shape={solution1.t.shape if hasattr(solution1, 't') else 'N/A'}"
)

print("\n" + "=" * 80)
print(
    "TEST 2: State continuation - check solution.cycles with set_initial_conditions_from()"
)
print("=" * 80)

# Create second model with state continuation
model2 = pybamm.lithium_ion.DFN(options=model_options)
model2_with_state = model2.set_initial_conditions_from(solution1, inplace=False)

print(f"\nModel2 created with set_initial_conditions_from()")
print(f"  Model2 == Model2_with_state: {model2 is model2_with_state}")

# Create another experiment for 2 more cycles
experiment2 = pybamm.Experiment(
    [
        "Discharge at 161.1 A until 2.5 V",
        "Charge at 80.55 A until 4.2 V",
        "Discharge at 161.1 A until 2.5 V",
        "Charge at 80.55 A until 4.2 V",
    ],
    period="1 minute",
)

sim2 = pybamm.Simulation(
    model2_with_state,
    experiment=experiment2,
    parameter_values=params,
    var_pts={"x_n": 10, "x_s": 10, "x_p": 10, "r_n": 30, "r_p": 30},
)

solution2 = sim2.solve(
    initial_soc=0.95, solver=solver
)  # Use 95% SoC to match degraded state

print(f"\nSolution 2 (next 2 cycles after state continuation):")
print(f"  solution.cycles exists: {hasattr(solution2, 'cycles')}")
if hasattr(solution2, "cycles"):
    print(f"  len(solution.cycles): {len(solution2.cycles)}")
print(
    f"  solution.t (time): shape={solution2.t.shape if hasattr(solution2, 't') else 'N/A'}"
)

# Try to extract first cycle from solution2
print(f"\nAttempting cycle extraction from solution2:")
if hasattr(solution2, "cycles") and len(solution2.cycles) > 0:
    print(f"  Cycle[0] type: {type(solution2.cycles[0])}")
    try:
        cap = solution2.cycles[0]["Discharge capacity [A.h]"].entries
        print(f"  Cycle[0] capacity entries: {cap}")
    except Exception as e:
        print(f"  ERROR accessing Cycle[0] data: {e}")
else:
    print(f"  No cycles found in solution2!")
    print(
        f"  Available solution attributes: {[attr for attr in dir(solution2) if not attr.startswith('_')][:10]}"
    )

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)
print("The issue: solution.cycles may be empty or incorrectly structured when")
print(
    "using set_initial_conditions_from(). We may need alternative extraction methods."
)
