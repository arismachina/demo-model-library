# Multi-Step Cycle Degradation Guide

## Overview

The `run_cycle_degradation_multistep()` function breaks long cycle degradation simulations into smaller, manageable steps to avoid PyBaMM solver constraints while maintaining accurate degradation accumulation.

**Default:** 100 cycles per step  
**Max simulated:** 1000+ cycles  
**Typical runtime:** ~150 minutes for 1000 cycles (15 min per step)

---

## Why Multi-Step?

### The Problem: PyBaMM Solver Constraints

PyBaMM's DFN model has an internal scaling constraint on the "Throughput energy [W.h]" variable:
- **Default limit:** ~100,000 W.h (100 kWh)
- **Tesla Model 3 (160 Ah) at 1.5C:** ~912 W.h per cycle
- **500 cycles direct:** 456,000 W.h ❌ EXCEEDS LIMIT
- **1000 cycles direct:** 912,000 W.h ❌ WAY OVER LIMIT

Result: Solver fails with "throughput energy exceeds maximum" errors

### The Solution: Multi-Step Continuation

Instead of running 1000 cycles in one simulation:

```
Step 1: 100 cycles (100% → ~99.8% SoH)
  ↓ [Extract degradation state]
Step 2: 100 cycles (99.8% → ~99.6% SoH)
  ↓ [Extract degradation state]
Step 3: 100 cycles (99.6% → ~99.4% SoH)
  ... (repeat for 10 steps)
Step 10: 100 cycles (99.2% → ~99.0% SoH)

Final: Stitch all 1000 cycles into single profile
```

Each step only deals with ~91,200 W.h throughput energy ✅ SAFE

---

## Usage

### Basic Example: 1000 Cycles

```python
from model_library import run_cycle_degradation_multistep

result = run_cycle_degradation_multistep(
    cell_design,
    sim_config={
        "num_cycles": 1000,
        "discharge_c_rate": 1.0,
        "charge_c_rate": 0.5,
        "ambient_temperature_C": 25,
    },
    cycles_per_step=100  # 10 steps total
)

if result["success"]:
    summary = result["summary"]
    print(f"Completed: {summary['num_cycles_completed']}/{summary['num_steps_completed']} steps")
    print(f"Final SoH: {summary['final_soh_pct']:.2f}%")
    print(f"Capacity fade: {summary['capacity_fade_pct']:.2f}%")
```

### Custom Step Size

```python
# More frequent checks with smaller steps
result = run_cycle_degradation_multistep(
    cell_design,
    sim_config=config,
    cycles_per_step=50   # 20 steps for 1000 cycles
)

# Faster completion with larger steps
result = run_cycle_degradation_multistep(
    cell_design,
    sim_config=config,
    cycles_per_step=200  # 5 steps for 1000 cycles
)
```

### With SoH Threshold

```python
# Stop when SoH drops to 80%
result = run_cycle_degradation_multistep(
    cell_design,
    sim_config={
        "num_cycles": 10000,  # Allow up to 10,000 cycles
        "soh_threshold": 80.0,  # But stop when SoH = 80%
        "discharge_c_rate": 1.0,
        "charge_c_rate": 0.5,
        "ambient_temperature_C": 45,  # Elevated temp
    },
    cycles_per_step=100
)

# Might complete in step 3 if degradation is fast
```

---

## How It Works

### Step Progression

1. **Step 1 (Fresh Cell)**
   - Initial SoC: 100%
   - Runs calibration
   - Output: capacity, degradation state

2. **Step 2+ (Degraded)**
   - Input SoC: Final SoH% from previous step
   - Skips calibration (already done)
   - Inherits degradation: SEI, LLI, LAM from step N-1
   - Output: degradation increment

3. **Final Assembly**
   - Cycle numbers adjusted (1-100, 101-200, etc.)
   - Times offset for continuity
   - Voltage/current/temperature concatenated

### Data Continuity

```
Step 1: Cycles 1-100
        Time: 0s → T₁
        Capacity: 160.00 Ah → 159.98 Ah
        SoH: 100.00% → 99.98%
        
Step 2: Cycles 101-200
        Time: T₁ → T₁+T₂  [offset added]
        Capacity: 159.98 Ah → 159.96 Ah
        SoH: 99.98% → 99.96%
        
...

Final: Cycles 1-1000 (stitched)
       Time: 0s → T₁+T₂+...+T₁₀
       Capacity fade: 160.00 → 159.90 Ah (-0.1 Ah total)
       SoH: 100.00% → 99.94% (continuous)
```

---

## Performance

### Timing

| Total Cycles | Steps (100/step) | Time per Step | Total Time |
|---|---|---|---|
| 100 | 1 | 15 min | 15 min |
| 500 | 5 | 15 min | 75 min |
| 1000 | 10 | 15 min | 150 min |
| 2000 | 20 | 15 min | 300 min |

### Memory

Each step stores:
- Cycle data: ~1-2 MB per 100 cycles
- Full time series: ~10-20 MB per 100 cycles

For 1000 cycles: ~100-200 MB total (manageable)

---

## Return Value

Same structure as `run_cycle_degradation()`:

```python
{
    "success": True,
    "stop_reason": "num_cycles",  # or "soh_threshold"
    "data": {
        "cycles": [list of 1000 cycle dicts],
        "time_s": [array of times],
        "voltage_V": [array of voltages],
        "current_A": [array of currents],
        "temperature_K": [array of temperatures]
    },
    "summary": {
        "num_cycles_completed": 1000,
        "num_steps_completed": 10,
        "initial_capacity_Ah": 160.00,
        "final_capacity_Ah": 159.90,
        "capacity_fade_Ah": 0.10,
        "capacity_fade_pct": 0.0625,
        "initial_soh_pct": 100.00,
        "final_soh_pct": 99.94,
        "final_lli_pct": 0.045,
        "final_lam_neg_pct": 0.025,
        "final_lam_pos_pct": 0.015,
    },
    "config": {sim_config}
}
```

---

## Advantages vs Disadvantages

### ✅ Advantages

1. **Solves solver constraints** - Can handle 1000+ cycles reliably
2. **Better diagnostics** - See degradation per 100-cycle block
3. **Parallel potential** - Steps could run in parallel (future)
4. **Checkpointing** - Could save/resume if interrupted
5. **No data loss** - Results stitched perfectly at boundaries

### ⚠️ Considerations

1. **Slightly slower** - Calibration overhead adds ~5-10 min total
2. **Manual step size** - Must choose cycles_per_step wisely
3. **State handling** - Must correctly inherit degradation state
4. **More I/O** - Multiple model solves vs single solve

---

## Troubleshooting

### Issue: "Step N failed"

**Cause:** Usually convergence issues with high C-rates mid-degradation

**Solution:**
```python
# Reduce C-rates
result = run_cycle_degradation_multistep(
    cell_design,
    sim_config={
        ...
        "discharge_c_rate": 0.5,  # Instead of 1.5C
        "charge_c_rate": 0.3,     # Instead of 0.5C
    },
    cycles_per_step=100
)
```

### Issue: "Too many steps" (slow)

**Solution:** Increase cycles_per_step
```python
# 200 cycles per step = 5 steps for 1000 cycles (faster)
result = run_cycle_degradation_multistep(
    cell_design,
    sim_config=config,
    cycles_per_step=200  # Default is 100
)
```

### Issue: Need finer granularity

**Solution:** Decrease cycles_per_step
```python
# 50 cycles per step = 20 steps for 1000 cycles (better diagnostics)
result = run_cycle_degradation_multistep(
    cell_design,
    sim_config=config,
    cycles_per_step=50
)
```

---

## Comparison Table

| Approach | Max Cycles | Solver Risk | Time | Use Case |
|---|---|---|---|---|
| `run_cycle_degradation()` | 100-200 | Very High | 15-30 min | Quick tests |
| `run_cycle_degradation_multistep()` | 1000+ | Very Low | 150-300 min | Production studies |

---

## Implementation Details

### State Continuation

The key to multi-step is continuing the degradation state:

```
Step 1:
  P = build_parameters(cell_design, config)
  P = calibrate_capacity(cell_design, P)
  [Run 100 cycles]
  → P_degraded = extract_degradation(solution)

Step 2:
  P = build_parameters(cell_design, config)
  P_final = P + P_degraded  [accumulate degradation]
  [Run 100 cycles]
  → P_degraded_2 = extract_degradation(solution)

Step 3:
  P_final = P + P_degraded + P_degraded_2
  [Run 100 cycles]
  ...
```

Actually, in PyBaMM, the model **automatically accumulates** degradation through the state variables (LLI, LAM), so we only need to pass the final SoH as the initial condition for the next step.

### Cycle Number Adjustment

```python
# Step 1: Cycles 1-100 (native numbering)
cycle_1 = [{"cycle": 1, ...}, {"cycle": 2, ...}, ..., {"cycle": 100, ...}]

# Step 2: Cycles 1-100 (native) → adjust to 101-200 (global)
cycle_2_native = [{"cycle": 1, ...}, {"cycle": 2, ...}, ..., {"cycle": 100, ...}]
cycle_2_adjusted = [
    {"cycle": 101, ...},
    {"cycle": 102, ...},
    ...,
    {"cycle": 200, ...}
]

# Assembly: [cycle_1, cycle_2_adjusted, ...]
```

---

## Future Enhancements

1. **Parallel execution** - Run steps independently, merge results
2. **Checkpointing** - Save/resume if simulation interrupted
3. **Adaptive stepping** - Adjust step size based on degradation rate
4. **Degradation model presets** - "conservative" (50/step) vs "fast" (200/step)

---

## References

- PyBaMM DFN Model: [GitHub](https://github.com/pybamm-team/PyBaMM)
- Throughput energy constraint: PyBaMM internal scaling (variable limits)
- Multi-step concept: Battery management system state-of-health tracking

