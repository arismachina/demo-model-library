# PyBaMM State Continuation & Multi-Solve Patterns

## Summary

This document provides specific code examples from the `model_library` codebase showing how PyBaMM solutions are used to initialize subsequent simulations, pass state vectors between solve() calls, and implement multi-step degradation patterns.

---

## 1. Multi-Step Cycle Degradation Pattern

**File:** `/Users/manik/Github/model_library/src/model_library/dfn_cycle_degradation.py`

This is the primary example of state continuation in the codebase. The pattern breaks a long simulation (>150 cycles) into smaller steps to avoid PyBaMM's solver constraints on throughput energy.

### Key Architecture:

```python
def run_cycle_degradation_multistep(
    cell_design: Dict, 
    sim_config: Dict, 
    cycles_per_step: int = 100
) -> Dict[str, Any]:
    """
    Run DFN cycle degradation simulation using multi-step approach.
    
    Breaks the total simulation into steps (default 100 cycles per step),
    continuing degradation state from end of previous step to next step.
    This avoids PyBaMM solver constraints on throughput energy.
    """
    
    # Initialize storage for accumulated data
    all_cycle_data = []
    all_times = []
    all_voltages = []
    all_currents = []
    all_temperatures = []
    
    current_soc = sim_config.get("initial_soc", 1.0)
    final_state_vector = None  # Initialize for first step
    
    for step_num in range(num_steps):
        # Create config for this step
        step_config = sim_config.copy()
        step_config["num_cycles"] = cycles_this_step
        step_config["initial_soc"] = current_soc
        step_config["skip_capacity_calibration"] = (step_num > 0)
        step_config["_skip_multistep_delegation"] = True
        
        # Pass final state vector from previous step if available
        if step_num > 0 and final_state_vector is not None:
            print(f"  Passing state vector from Step {current_step_num-1}")
            step_config["_initial_y0"] = final_state_vector
        
        # Run this step (recursive call to single-step function)
        result = run_cycle_degradation(cell_design, step_config)
        
        # Extract final state vector for next step
        if "final_state_vector" in result:
            final_state_vector = result["final_state_vector"]
        else:
            final_state_vector = None
        
        # Accumulate data from this step...
        # Update SoC for next step
        final_soh = step_cycle_data[-1]["soh_pct"]
        current_soc = final_soh / 100.0
```

**Lines:** 281-437

### State Vector Extraction:

```python
# Extract final state vector at end of simulation (line 828)
final_state_vector = solution.y[:, -1]

return {
    "success": True,
    "stop_reason": stop_reason,
    "data": {...},
    "summary": summary,
    "config": sim_config,
    "final_state_vector": final_state_vector,  # For multi-step state continuation
}
```

**Lines:** 828-842

### Current Limitation (State Vector Not Yet Integrated):

```python
# Use initial state vector from previous step if available (multi-step mode)
# PyBaMM's Experiment-based solver doesn't directly support y0 parameter
# Degradation state is managed by the model equations themselves
# For true state continuation, would need to use direct solver API (not Experiment)

if "_initial_y0" in sim_config:
    print(f"  ⚠️  State vector initialization not yet fully implemented")
    print(f"     (Requires custom solver integration)")

solution = sim.solve(initial_soc=initial_soc, solver=solver)
```

**Lines:** 671-691

---

## 2. State Vector Structure

### What is `solution.y`?

- **`solution.y`**: A numpy array containing all state variables over time
  - Shape: `(n_states, n_time_points)`
  - `n_states`: Total number of differential equations in the model
  - `n_time_points`: Number of time steps in the solution
  
- **`solution.y[:, -1]`**: The final state vector at the end of the simulation
  - Contains all state variables at the last time point
  - Dimension: `(n_states,)` 
  - Ready to be used as initial condition for next simulation

### Example Usage:

```python
# Extract final state from a solution
final_state_vector = solution.y[:, -1]  # Shape: (n_states,)

# For next solve, would ideally pass as:
# solver.solve(model, t_eval, y0=final_state_vector)
```

---

## 3. DFN Cycle Degradation: Auto-Delegation Pattern

**File:** `/Users/manik/Github/model_library/src/model_library/dfn_cycle_degradation.py`

The codebase includes automatic delegation from single-step to multi-step based on cycle count:

```python
def run_cycle_degradation(cell_design: Dict, sim_config: Dict) -> Dict[str, Any]:
    """Main cycle degradation function with auto-delegation."""
    
    num_cycles = sim_config.get("num_cycles", 100)
    force_single_step = sim_config.get("_skip_multistep_delegation", False)
    
    # Auto-delegate to multi-step if >150 cycles
    if num_cycles > 150 and not force_single_step:
        print("\n" + "=" * 80)
        print("AUTO-DELEGATING TO MULTI-STEP APPROACH")
        print("=" * 80)
        print(f"\nDetected {num_cycles} cycles (>150 cycle threshold)")
        print("Automatically using multi-step to avoid PyBaMM solver constraints")
        print(f"  • Breaking into steps of 100 cycles each ({(num_cycles + 99) // 100} steps)")
        print(f"  • Each step: ~60 kWh throughput (safe)")
        print(f"  • Single-step would be: ~{num_cycles * 60 / 100:.0f} kWh (potentially unsafe)")
        print("=" * 80 + "\n")
        
        return run_cycle_degradation_multistep(cell_design, sim_config, cycles_per_step=100)
```

**Lines:** 541-555

### Why Multi-Step?

- **PyBaMM Constraint:** Max throughput energy per solve is ~500 kWh (configured via `pybamm.settings.max_y_value`)
- **1000 cycles @ 1C:** ~600 kWh → exceeds limit ❌
- **100 cycles @ 1C (per step):** ~60 kWh → safe ✅

---

## 4. Practical Multi-Solve Example from Notebook

**File:** `/Users/manik/Github/model_library/notebooks/simulate_cycle_degradation.ipynb`

Demonstrates how to use the multi-step degradation function:

```python
# Simple configuration requesting 1000 cycles
sim_config = {
    "num_cycles": 1000,           # Auto-delegates to multi-step (>150 cycles)
    "soh_threshold": 80.0,        # Stop if SoH reaches 80%
    "discharge_c_rate": 1.0,      # 1C discharge
    "charge_c_rate": 0.5,         # C/2 charge
    "initial_soc": 1.0,
    "ambient_temperature_C": 45,
}

# Single call - function handles multi-step automatically!
result = run_cycle_degradation(cell_design, sim_config)

if result["success"]:
    summary = result["summary"]
    print(f"Cycles completed: {summary['num_cycles_completed']}/1000")
    print(f"Final SoH: {summary['final_soh_pct']:.2f}%")
    
    # Check if multi-step was used
    if "num_steps_completed" in summary:
        print(f"Steps completed: {summary['num_steps_completed']}")
```

---

## 5. Capacity Calibration with Iterative Solves

**File:** `/Users/manik/Github/model_library/src/model_library/dfn_cycle_degradation.py` (lines 160-200)

Example of iterative solve pattern for convergence:

```python
def _build_pybamm_params(cell_design: dict, simulation_config: dict) -> tuple:
    """Build PyBaMM parameters from cell design manifest."""
    
    MAX_ITERATIONS = 20
    TOLERANCE = 0.0001
    
    for iteration in range(MAX_ITERATIONS):
        # Create fresh simulation for this iteration
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=default_params,
        )
        
        # Solve the simulation
        sol_capacity = sim_capacity.solve(
            solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
        )
        
        # Extract results to check convergence
        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            break
        
        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )
        
        scale_factor = discharge_capacity / target_capacity_Ah
        error_percent = abs(1 - scale_factor) * 100
        
        print(f"Iteration {iteration+1:2d}: Capacity = {discharge_capacity:6.2f} Ah, "
              f"Error = {error_percent:6.3f}%")
        
        if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
            print(f"Converged after {iteration+1} iterations!")
            
            # Extract final OCV values from solution
            ocv_100 = float(sol_capacity.cycles[1]["Terminal voltage [V]"].entries[-1])
            ocv_0 = float(sol_capacity.cycles[3]["Terminal voltage [V]"].entries[-1])
            
            # Update parameters with final values
            default_params.update(
                {
                    "Open-circuit voltage at 100% SOC [V]": ocv_100,
                    "Open-circuit voltage at 0% SOC [V]": ocv_0,
                },
                check_already_exists=False,
            )
            break
        
        # Adjust electrode width for next iteration
        new_width = default_params["Electrode width [m]"] / scale_factor
        default_params.update(
            {
                "Electrode width [m]": new_width,
                "Nominal cell capacity [A.h]": discharge_capacity / scale_factor,
            },
            check_already_exists=False,
        )
```

**Pattern:** Iterative solves with result extraction and parameter update

---

## 6. Direct Solution Object Access Patterns

From the grep search, the key pattern for accessing solution data is:

```python
# Basic solve call (Experiment-based)
solution = sim.solve(initial_soc=initial_soc, solver=solver)

# Access solution data
time_s = solution["Time [s]"].entries
voltage_V = solution["Terminal voltage [V]"].entries
current_A = solution["Current [A]"].entries
temperature_K = solution["Volume-averaged cell temperature [K]"].entries

# Access cycle-by-cycle data
for i, cycle in enumerate(solution.cycles):
    cycle_data = cycle["Discharge capacity [A.h]"].entries
    degradation_lli = cycle["Loss of lithium inventory [%]"].entries[-1]

# Access state vector
final_state = solution.y[:, -1]  # Final state at last time point
all_states = solution.y[:, :]    # All states over entire time span
```

---

## 7. Summary of Findings

### What's Implemented ✅
1. **State vector extraction:** `solution.y[:, -1]` to get final state
2. **Multi-step orchestration:** Breaking large simulations into smaller steps
3. **Data accumulation:** Combining results across steps
4. **SOC propagation:** Using final SoH to initialize next step
5. **Solution object access:** Full data extraction from `pybamm.Solution`

### What's NOT Yet Fully Implemented ❌
1. **Direct y0 initialization:** PyBaMM's Experiment-based Simulation class doesn't natively support passing initial state vector (`y0`) parameter
2. **Custom solver API:** Would require using lower-level solver methods instead of `Simulation.solve()`
3. **Stateful continuation:** The degradation state is currently tracked through the model equations, not explicitly through y0

### Required for True State Continuation
To fully pass state vectors between solves would require:

```python
# Pseudo-code (not currently in use):
# Instead of:
solution = sim.solve(initial_soc=initial_soc)

# Would need something like:
solver = pybamm.IDAKLUSolver()
discretisation = pybamm.Discretisation()
disc_model = discretisation.process_model(model)

# First solve
sol1 = solver.solve(disc_model, t_eval=[0, t1], y0=initial_y0)
y_final = sol1.y[:, -1]

# Second solve with state continuation
sol2 = solver.solve(disc_model, t_eval=[t1, t2], y0=y_final)
```

---

## 8. Code File Locations Summary

| Pattern | File | Lines | Status |
|---------|------|-------|--------|
| Multi-step orchestration | `dfn_cycle_degradation.py` | 281-437 | ✅ Implemented |
| State vector extraction | `dfn_cycle_degradation.py` | 828 | ✅ Implemented |
| State vector passing config | `dfn_cycle_degradation.py` | 357, 671 | ⏳ Configured but not used |
| Iterative capacity calibration | `dfn_cycle_degradation.py` | 160-200 | ✅ Implemented |
| Auto-delegation logic | `dfn_cycle_degradation.py` | 541-555 | ✅ Implemented |
| Cycle-by-cycle extraction | `dfn_cycle_degradation.py` | 707-770 | ✅ Implemented |
| Similar patterns in other modules | `spmet.py`, `spmet_drive.py`, `spmet_bess.py` | Various | ✅ Similar patterns |
| Notebook demonstration | `notebooks/simulate_cycle_degradation.ipynb` | Line 291-321 (selected) | ✅ Example usage |

---

## 9. Related Documentation

- `DFN_CALENDAR_DEGRADATION_SUMMARY.md` - DFN model details
- `MULTI_CYCLE_INTEGRATION.md` - Integration patterns
- `MULTI_STEP_CYCLING_GUIDE.md` - Multi-step methodology guide
