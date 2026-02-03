# PyBaMM State Continuation: Technical Deep Dive

## Overview

This document provides detailed technical analysis of how PyBaMM solutions are used for state continuation in the model_library codebase, with focus on the barriers and workarounds to the Experiment-based API limitations.

---

## Part 1: The Problem - PyBaMM's Throughput Energy Constraint

### Why Multi-Step is Necessary

PyBaMM enforces a maximum throughput energy limit per solve call to prevent numerical issues:

```python
pybamm.settings.max_y_value = 500000.0  # 500 kWh limit
```

For a large cylindrical cell (22 Ah @ 3.7V nominal):
- **Energy per cycle:** ~80 Wh (22 Ah × 3.7V)
- **150 cycles:** 12 kWh ✅ Safe
- **1000 cycles:** 80 kWh per step ✅ Safe (100 cycles/step)
- **1000 cycles single-step:** 80 kWh ✓ Actually safe for this cell...

However for larger cells like BYD Blade (135 Ah):
- **Energy per cycle:** ~500 Wh (135 Ah × 3.7V)
- **150 cycles:** 75 kWh ✅ Safe
- **1000 cycles:** 500 kWh ✅ At limit (100 cycles/step)
- **1000 cycles single-step:** 500+ kWh ❌ Exceeds limit

---

## Part 2: Multi-Step Implementation Details

### Architecture Flow Diagram

```
User calls: run_cycle_degradation(cell_design, sim_config)
    │
    ├─ num_cycles > 150?
    │   ├─ YES → Call run_cycle_degradation_multistep()
    │   └─ NO  → Execute single-step directly
    │
    └─ run_cycle_degradation_multistep() Loop:
        ├─ Step 1: run_cycle_degradation(..., cycles=100, initial_soc=1.0)
        │   ├─ Execute simulation
        │   ├─ Extract: final_state_vector = solution.y[:, -1]
        │   ├─ Extract: final_soh = cycle_data[-1]["soh_pct"]
        │   └─ Store data
        │
        ├─ Step 2: run_cycle_degradation(..., cycles=100, initial_soc=final_soh/100)
        │   ├─ Config includes: step_config["_initial_y0"] = final_state_vector
        │   ├─ Execute simulation (state vector currently ignored ⚠️)
        │   ├─ Extract: final_state_vector = solution.y[:, -1]
        │   └─ Store data
        │
        └─ Steps 3-N: Same as Step 2
```

### Step Configuration (Key Lines)

From `dfn_cycle_degradation.py` lines 331-357:

```python
for step_num in range(num_steps):
    current_step_num = step_num + 1
    
    # Calculate cycles for this step
    cycles_remaining = total_cycles - len(all_cycle_data)
    cycles_this_step = min(cycles_per_step, cycles_remaining)
    
    # Create config for this step
    step_config = sim_config.copy()
    step_config["num_cycles"] = cycles_this_step
    step_config["initial_soc"] = current_soc  # ← Updated from final SoH
    step_config["skip_capacity_calibration"] = (step_num > 0)
    step_config["_skip_multistep_delegation"] = True  # Prevent recursion
    
    # Pass final state vector from previous step if available
    if step_num > 0 and final_state_vector is not None:
        print(f"  Passing state vector from Step {current_step_num-1}")
        step_config["_initial_y0"] = final_state_vector  # ← State vector config
    
    # Run this step
    result = run_cycle_degradation(cell_design, step_config)
    
    # Extract final state vector for next step
    if "final_state_vector" in result:
        final_state_vector = result["final_state_vector"]
    else:
        final_state_vector = None
```

### State Vector Extraction (Line 828)

```python
# At end of single-step simulation
final_state_vector = solution.y[:, -1]

# Return in result dictionary
return {
    "success": True,
    "data": {...},
    "summary": summary,
    "config": sim_config,
    "final_state_vector": final_state_vector,  # ← For multi-step continuation
}
```

---

## Part 3: The Limitation - Experiment-Based Solver API

### Current Implementation

```python
# Line 691: How simulation is currently solved
solution = sim.solve(initial_soc=initial_soc, solver=solver)
```

The `pybamm.Simulation` class with `Experiment` only supports:
- `initial_soc`: Initial state of charge
- `solver`: Which solver to use
- **NO** `y0` parameter for initial state vector

### Why This Matters

PyBaMM tracks degradation mechanisms (SEI growth, lithium loss, etc.) through the model equations themselves. Between steps:

| Property | How It's Handled |
|----------|-----------------|
| **Electrical state** (Li concentration, voltage) | Implicitly via initial_soc |
| **Degradation state** (SEI thickness, LLI) | Model equations re-solve from initial conditions |
| **Mechanical state** | Not tracked in electrochemical model |

**Problem:** The degradation parameters (SEI thickness, etc.) are reset to initial values at each step's boundaries, even though the physical cell has degraded.

**Current Workaround:** The `initial_soc` parameter indirectly affects degradation by changing the electrochemical operating point for the next step.

### Pseudocode: What True State Continuation Would Look Like

```python
# This is NOT currently possible with pybamm.Simulation.solve()

# Step 1: Initial simulation
sim1 = pybamm.Simulation(model, experiment=experiment1, ...)
sol1 = sim1.solve(initial_soc=1.0)
y_final = sol1.y[:, -1]  # ← Final state including all degradation states

# Step 2: Continue with final state as initial condition
# ❌ This doesn't work with Simulation class:
# sim2 = pybamm.Simulation(...)
# sol2 = sim2.solve(initial_soc=0.9, y0=y_final)  # ← y0 parameter not supported!

# ✅ Would need direct solver API:
solver = pybamm.IDAKLUSolver()
disc = pybamm.Discretisation()
disc_model = disc.process_model(model)
sol2 = solver.solve(disc_model, t_eval=t2, y0=y_final)  # ← Raw solver API
```

---

## Part 4: Data Accumulation Across Steps

### How Results Are Merged (Lines 376-410)

```python
# Accumulate cycle data (with cycle number adjustment)
step_cycle_data = result["data"]["cycles"]
step_start_cycle = len(all_cycle_data) + 1

for cycle in step_cycle_data:
    cycle["cycle"] = step_start_cycle + (cycle["cycle"] - 1)
    all_cycle_data.append(cycle)

# Accumulate time series (with time offset for continuity)
time_offset = all_times[-1] if all_times else 0
step_times = result["data"]["time_s"]

if isinstance(step_times, np.ndarray):
    step_times = step_times.flatten()
else:
    step_times = np.array(step_times)

all_times.extend(step_times + time_offset)  # ← Offset for seamless continuation
all_voltages.extend(result["data"]["voltage_V"])
all_currents.extend(result["data"]["current_A"])
all_temperatures.extend(result["data"]["temperature_K"])

# Update SoC for next step
final_soh = step_cycle_data[-1]["soh_pct"]
current_soc = final_soh / 100.0
```

### Example: 200 Cycles, 100 Cycles/Step

**Step 1 Result:**
```
cycles: [1, 2, 3, ..., 100]
time: [0, 1.5, 3.0, ..., 150] seconds
final_soh: 98.5%
```

**Step 2 Input:**
```
initial_soc: 0.985
```

**Step 2 Result** (before adjustment):
```
cycles: [1, 2, 3, ..., 100]
time: [0, 1.5, 3.0, ..., 150] seconds
```

**After Accumulation:**
```
cycles: [1, 2, ..., 100, 101, 102, ..., 200]
time: [0, 1.5, ..., 150, 151.5, 153.0, ..., 300]
final_soh: 97.0%
```

---

## Part 5: Comparison with Other Multi-Solve Patterns

### Pattern 1: Iterative Capacity Calibration

**Location:** `dfn_cycle_degradation.py` lines 160-200

```python
for iteration in range(MAX_ITERATIONS):
    # Create new simulation each iteration
    sim_capacity = pybamm.Simulation(
        model_capacity,
        experiment=capacity_match_experiment,
        parameter_values=default_params,
    )
    
    # Solve (independent of previous iteration)
    sol_capacity = sim_capacity.solve(
        solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
    )
    
    # Extract metrics to check convergence
    if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
        break
    
    discharge_cycle = sol_capacity.cycles[2]
    discharge_capacity = float(
        discharge_cycle["Discharge capacity [A.h]"].entries[-1]
        - discharge_cycle["Discharge capacity [A.h]"].entries[0]
    )
    
    # Check convergence
    scale_factor = discharge_capacity / target_capacity_Ah
    error_percent = abs(1 - scale_factor) * 100
    
    if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
        break
    
    # Update parameters for next iteration (convergence-driven)
    new_width = default_params["Electrode width [m]"] / scale_factor
    default_params.update(
        {"Electrode width [m]": new_width},
        check_already_exists=False,
    )
```

**Key Differences:**
- Uses **parameter updates** (not state vectors)
- Each solve is independent
- Convergence driven by extracted metrics

### Pattern 2: C-Rate Sweep with Fresh Solves

**Location:** `battery-data-analyzer/PyBaMM_Tutorial_Working.ipynb` (line 539+)

```python
c_rates = [0.1, 0.5, 1.0, 2.0]
solutions = {}

for c_rate in c_rates:
    print(f"Running {c_rate}C simulation...")
    
    # Update parameters
    param.update({
        # C-rate specific values
    }, check_already_exists=False)
    
    # Create fresh simulation
    sim = pybamm.Simulation(model, parameter_values=param)
    
    try:
        solution = sim.solve([0, 3600/c_rate])  # Adjust time for C-rate
        solutions[c_rate] = solution
        print(f"  ✓ {c_rate}C completed")
    except:
        print(f"  ⚠️  {c_rate}C failed")
```

**Key Differences:**
- Parameter sweep (not state continuation)
- Each simulation is independent
- No state passing between solves

### Pattern 3: Temperature-Dependent Parametric Study

**Location:** Various `spmet_*.py` files

```python
temperatures = [25, 35, 45, 55]

for temp in temperatures:
    # Update temperature parameter
    default_params.update({
        "Ambient temperature [K]": temp + 273.15,
        "Initial temperature [K]": temp + 273.15,
    }, check_already_exists=False)
    
    # Fresh simulation with updated params
    sim = pybamm.Simulation(...)
    solution = sim.solve(initial_soc=0.5)
    
    # Store results indexed by temperature
    results[temp] = extract_metrics(solution)
```

**Key Differences:**
- Parameter study (not state continuation)
- All simulations independent
- No state passing needed

---

## Part 6: Data Structures and Types

### Solution Object Structure

```python
solution = sim.solve(initial_soc=0.5, solver=solver)

# Types of access:
solution["Time [s]"]                              # Variable access
→ type: pybamm.SolutionVariable
→ .entries: numpy array of time points

solution["Terminal voltage [V]"]
→ type: pybamm.SolutionVariable
→ .entries: numpy array of voltages

solution.cycles                                   # Cycle-by-cycle data
→ type: list of pybamm.Solution (one per cycle)
→ can be indexed: solution.cycles[0]

solution.y                                        # State vector array
→ type: numpy.ndarray
→ shape: (n_states, n_time_points)
→ solution.y[:, 0]: Initial state vector
→ solution.y[:, -1]: Final state vector
→ solution.y[i, :]: Time series of i-th state variable
```

### Example: Extracting Cycle-by-Cycle Data

```python
for cycle_idx, cycle in enumerate(solution.cycles):
    # Access variables within this cycle
    discharge_capacity = cycle["Discharge capacity [A.h]"].entries
    
    # Time series data (numpy arrays)
    voltage_data = discharge_capacity[-1] - discharge_capacity[0]
    
    # Degradation metrics (if available)
    try:
        lli = cycle["Loss of lithium inventory [%]"].entries[-1]
    except:
        lli = 0.0
```

---

## Part 7: Performance Characteristics

### Timing Data (Empirical from Notebook Tests)

From `notebooks/simulate_cycle_degradation.ipynb`:

| Test Case | Cycles | Configuration | Est. Time |
|-----------|--------|----------------|-----------|
| Standard | 10 | 1C discharge / 0.5C charge | 5 min |
| Standard | 100 | 1C discharge / 0.5C charge | 50 min |
| Fast charge | 10 | 1.5C discharge / 1C charge | 6 min |
| Multi-step | 1000 | 10 steps × 100 cycles | 150 min (10-15 min/step) |

### Memory Usage Pattern

```python
# Single-step 1000 cycles (if it worked):
# Memory = solution.y shape of (~100 states, ~1M time points)
# → Large memory footprint, numerical issues

# Multi-step 10 × 100 cycles:
# Each step: solution.y shape (~100 states, ~100K time points)
# Memory = smaller per step, can discard after extraction
# → Lower peak memory, better numerical stability

# Data accumulation (lines 376-410):
all_cycle_data = []        # List of dicts, linear growth
all_times = []             # Growing numpy array
all_voltages = []          # Growing numpy array
```

---

## Part 8: Configuration Parameters

### Main Simulation Config (from docstrings)

```python
sim_config = {
    # Cycle control
    "num_cycles": int,                    # Total cycles (auto-delegates if >150)
    "discharge_c_rate": float,            # C-rate for discharge (e.g., 1.0 = 1C)
    "charge_c_rate": float,               # C-rate for charge
    
    # Initial conditions
    "initial_soc": float,                 # Initial state of charge (0-1)
    "ambient_temperature_C": float,       # Ambient temp in Celsius
    
    # Stopping criteria
    "soh_threshold": float,               # Stop if SoH drops below this (%)
    
    # Solver settings
    "solver_atol": float,                 # Absolute tolerance (default: 1e-4)
    "solver_rtol": float,                 # Relative tolerance (default: 1e-4)
    
    # Internal flags (multi-step)
    "_skip_multistep_delegation": bool,   # Skip auto-delegation (forces single-step)
    "_initial_y0": numpy.ndarray,         # Initial state vector (currently unused)
    "_skip_capacity_calibration": bool,   # Skip calibration in step 2+
}
```

### Step Configuration (from lines 331-357)

```python
step_config = sim_config.copy()
step_config["num_cycles"] = cycles_this_step  # Reduced for this step
step_config["initial_soc"] = current_soc      # Updated from final SoH
step_config["skip_capacity_calibration"] = (step_num > 0)  # Only first step
step_config["_skip_multistep_delegation"] = True           # Prevent recursion
step_config["_initial_y0"] = final_state_vector            # For future use
```

---

## Part 9: Known Limitations and Future Work

### Current Limitations

1. **State Vector Not Used**: The `_initial_y0` is extracted and passed but not actually used in the solver
   - Would require custom solver integration
   - Simulation class API doesn't support direct y0 parameter

2. **Degradation State Reset**: Each step resets degradation mechanisms
   - SEI thickness re-initializes
   - Lithium inventory loss tracks only within step
   - Only workaround: use final SoH as next step's initial_soc

3. **Experiment-Based Only**: Cannot use lower-level solver API
   - Would need to abandon pybamm.Simulation.solve()
   - Requires manual discretization and solver setup
   - Loss of built-in convenience functions

### To Implement True State Continuation

```python
# Pseudo-implementation (not in current codebase):

class DirectSolverMultiStep:
    def __init__(self, model, experiment, parameters):
        self.model = model
        self.parameters = parameters
        self.discretisation = pybamm.Discretisation()
        self.solver = pybamm.IDAKLUSolver()
    
    def solve_step(self, t_eval, y0=None):
        """Solve a single step with optional initial state vector."""
        disc_model = self.discretisation.process_model(self.model)
        sol = self.solver.solve(disc_model, t_eval, y0=y0)
        return sol
    
    def solve_multistep(self, cycles_per_step=100, total_cycles=1000):
        """Solve multiple steps with state continuation."""
        y_current = None
        all_solutions = []
        
        for step in range(0, total_cycles, cycles_per_step):
            t_eval = [step * t_cycle, (step + cycles_per_step) * t_cycle]
            sol = self.solve_step(t_eval, y0=y_current)
            
            all_solutions.append(sol)
            y_current = sol.y[:, -1]  # ← True state continuation!
        
        return self.combine_solutions(all_solutions)
```

---

## Part 10: Testing and Validation

### Multi-Step Validation Points

From `notebooks/simulate_cycle_degradation.ipynb`:

```python
# Test 1: Standard configuration (100 cycles, single-step)
result_standard = run_cycle_degradation(cell_design, {
    "num_cycles": 100,
    "discharge_c_rate": 1.0,
    "charge_c_rate": 0.5,
})
assert result_standard["summary"]["num_cycles_completed"] == 100

# Test 2: Multi-step auto-delegation (1000 cycles)
result_multi = run_cycle_degradation(cell_design, {
    "num_cycles": 1000,  # Will auto-delegate to multi-step
})
assert result_multi["summary"]["num_cycles_completed"] == 1000

# Test 3: Early termination via SoH threshold
result_soh = run_cycle_degradation(cell_design, {
    "num_cycles": 1000,
    "soh_threshold": 80.0,  # Stop when SoH reaches 80%
})
assert result_soh["summary"]["final_soh_pct"] <= 80.1

# Test 4: Temperature variation (multiple independent sims)
for temp in [25, 35, 45, 55]:
    result = run_cycle_degradation(cell_design, {
        "num_cycles": 100,
        "ambient_temperature_C": temp,
    })
    results[temp] = result["summary"]
```

---

## References

- **Primary Source:** `src/model_library/dfn_cycle_degradation.py` (860 lines)
- **Related:** `src/model_library/spmet.py`, `spmet_drive.py`, `spmet_bess.py`
- **Examples:** `notebooks/simulate_cycle_degradation.ipynb`
- **Documentation:** `DFN_CALENDAR_DEGRADATION_SUMMARY.md`, `MULTI_STEP_CYCLING_GUIDE.md`
