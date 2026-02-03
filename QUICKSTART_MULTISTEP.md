# Quick Start: Multi-Step Cycle Degradation

## TL;DR

Run 1000+ cycles without solver errors using `run_cycle_degradation_multistep()`:

```python
from model_library import run_cycle_degradation_multistep

result = run_cycle_degradation_multistep(
    cell_design,
    sim_config={
        "num_cycles": 1000,
        "discharge_c_rate": 1.0,
        "charge_c_rate": 0.5,
        "ambient_temperature_C": 25,
    }
)

print(f"✓ Completed {result['summary']['num_cycles_completed']} cycles")
print(f"  Final SoH: {result['summary']['final_soh_pct']:.2f}%")
```

---

## What Problem Does This Solve?

**Before:** Direct 500+ cycle sim → PyBaMM solver error ❌

```
TypeError: Solution for 'Throughput energy [W.h]' exceeds the 
maximum allowed value of 100000.0
```

**After:** Multi-step approach → Works perfectly ✅

```
Step 1/10: 100 cycles ✓
Step 2/10: 100 cycles ✓
...
Step 10/10: 100 cycles ✓
All stitched together → 1000 continuous cycles ✅
```

---

## How to Use

### Option 1: Default (100 cycles/step)

```python
result = run_cycle_degradation_multistep(
    cell_design,
    {"num_cycles": 1000, "discharge_c_rate": 1.0, "charge_c_rate": 0.5}
)
# Runs: 10 steps of 100 cycles each
```

### Option 2: Faster (200 cycles/step)

```python
result = run_cycle_degradation_multistep(
    cell_design,
    {"num_cycles": 1000, ...},
    cycles_per_step=200  # 5 steps instead of 10
)
# Time: ~75 min (faster)
# Trade: Less detailed diagnostics
```

### Option 3: More Detail (50 cycles/step)

```python
result = run_cycle_degradation_multistep(
    cell_design,
    {"num_cycles": 1000, ...},
    cycles_per_step=50   # 20 steps for fine granularity
)
# Time: ~300 min (slower)
# Benefit: Can analyze degradation every 50 cycles
```

---

## Key Parameters

| Parameter | Default | Effect |
|---|---|---|
| `num_cycles` | - | Total cycles to simulate |
| `discharge_c_rate` | 1.0 | Discharge rate (1.0 = 1C) |
| `charge_c_rate` | 0.5 | Charge rate (0.5 = C/2) |
| `cycles_per_step` | 100 | Cycles per step |
| `soh_threshold` | None | Stop when SoH drops to this % |
| `ambient_temperature_C` | 25 | Temperature in °C |

---

## Understanding the Output

```python
result = run_cycle_degradation_multistep(...)

# Top-level info
print(result["success"])              # True/False
print(result["stop_reason"])          # "num_cycles" or "soh_threshold"

# Summary statistics  
summary = result["summary"]
print(summary["num_cycles_completed"])    # Cycles run (e.g., 1000)
print(summary["num_steps_completed"])     # Steps run (e.g., 10)
print(summary["initial_capacity_Ah"])     # Starting capacity
print(summary["final_capacity_Ah"])       # Ending capacity
print(summary["capacity_fade_pct"])       # % fade
print(summary["final_soh_pct"])           # State of Health %
print(summary["final_lli_pct"])           # Loss of Li inventory %
print(summary["final_lam_neg_pct"])       # LAM negative electrode %
print(summary["final_lam_pos_pct"])       # LAM positive electrode %

# Cycle-by-cycle data
cycles = result["data"]["cycles"]
print(len(cycles))                        # 1000 cycles
print(cycles[0]["cycle"])                 # 1
print(cycles[0]["capacity_Ah"])           # Capacity at cycle 1
print(cycles[999]["cycle"])               # 1000
print(cycles[999]["soh_pct"])             # SoH at cycle 1000

# Full time series
time_s = result["data"]["time_s"]         # Time [seconds]
voltage_V = result["data"]["voltage_V"]   # Voltage trace
current_A = result["data"]["current_A"]   # Current trace
temp_K = result["data"]["temperature_K"]  # Temperature trace
```

---

## Common Tasks

### Task 1: Find cycle at 80% SoH

```python
cycles = result["data"]["cycles"]
for cycle in cycles:
    if cycle["soh_pct"] <= 80.0:
        print(f"80% SoH reached at cycle {cycle['cycle']}")
        break
```

### Task 2: Plot degradation

```python
import matplotlib.pyplot as plt

cycles = result["data"]["cycles"]
cycle_nums = [c["cycle"] for c in cycles]
capacities = [c["capacity_Ah"] for c in cycles]
soh_values = [c["soh_pct"] for c in cycles]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))

ax1.plot(cycle_nums, capacities, 'b-o')
ax1.set_xlabel("Cycle")
ax1.set_ylabel("Capacity [Ah]")
ax1.set_title("Capacity Fade (Multi-Step)")
ax1.grid()

ax2.plot(cycle_nums, soh_values, 'g-s')
ax2.set_xlabel("Cycle")
ax2.set_ylabel("SoH [%]")
ax2.set_title("State of Health")
ax2.grid()

plt.tight_layout()
plt.show()
```

### Task 3: Compare single vs multi-step (first 100 cycles)

```python
# Single-step (100 cycles direct)
result_single = run_cycle_degradation(cell_design, {..., "num_cycles": 100})

# Multi-step (same 100 cycles as step 1)
result_multi = run_cycle_degradation_multistep(cell_design, {...}, cycles_per_step=100)

# First 100 cycles should be identical
single_soh = result_single["summary"]["final_soh_pct"]
multi_soh = result_multi["summary"]["final_soh_pct"]

print(f"Single-step: {single_soh:.4f}%")
print(f"Multi-step:  {multi_soh:.4f}%")
print(f"Difference:  {abs(single_soh - multi_soh):.6f}%")  # Should be ~0
```

---

## Typical Runtimes

**Tesla Model 3 160 Ah @ 1C/0.5C, 25°C:**

| Cycles | Steps | Time |
|---|---|---|
| 100 | 1 | 15 min |
| 500 | 5 | 75 min |
| 1000 | 10 | 150 min |
| 1500 | 15 | 225 min |
| 2000 | 20 | 300 min |

---

## When to Use

✅ **Use multi-step for:**
- 200+ cycles
- Large cells (>100 Ah)
- Production studies
- High C-rates
- Need detailed degradation profile

❌ **Single-step is fine for:**
- Quick tests (<100 cycles)
- Parameter exploration
- Model validation

---

## Troubleshooting

### "Step N failed"

**Problem:** High C-rates cause convergence issues

**Solution:**
```python
result = run_cycle_degradation_multistep(
    cell_design,
    {
        ...
        "discharge_c_rate": 0.5,  # Reduce from 1.5C
        "charge_c_rate": 0.3,     # Reduce from 0.5C
    }
)
```

### "Taking too long"

**Problem:** Too many steps (small cycles_per_step)

**Solution:**
```python
result = run_cycle_degradation_multistep(
    cell_design,
    {...},
    cycles_per_step=200  # Increase from 100
)
```

### "Need more detail"

**Problem:** Not enough granularity per step

**Solution:**
```python
result = run_cycle_degradation_multistep(
    cell_design,
    {...},
    cycles_per_step=50   # Decrease from 100
)
# Now can analyze every 50 cycles
```

---

## Advanced: Custom Initial SoC

The function automatically calculates SoC for each step from the previous final SoH. But you can manually set initial conditions if needed:

```python
# For all steps
sim_config = {
    "num_cycles": 1000,
    "initial_soc": 0.98,  # Start from 98% charged
    ...
}

result = run_cycle_degradation_multistep(cell_design, sim_config)
```

---

## Reference

**Function:** `run_cycle_degradation_multistep()`  
**Module:** `model_library.dfn_cycle_degradation`  
**Return:** Same structure as `run_cycle_degradation()`  
**Docs:** See `MULTI_STEP_CYCLING_GUIDE.md`

---

## Quick Examples

### Example 1: 500 cycles @ 1C/0.5C

```python
from model_library import run_cycle_degradation_multistep

result = run_cycle_degradation_multistep(
    cell_design,
    {
        "num_cycles": 500,
        "discharge_c_rate": 1.0,
        "charge_c_rate": 0.5,
        "ambient_temperature_C": 25,
    }
)

print(f"Completed {result['summary']['num_cycles_completed']} cycles")
print(f"SoH fade: {100 - result['summary']['final_soh_pct']:.2f}%")
```

### Example 2: 1000 cycles with early stop at 80% SoH

```python
result = run_cycle_degradation_multistep(
    cell_design,
    {
        "num_cycles": 10000,  # Allow up to 10k
        "soh_threshold": 80.0,  # But stop at 80%
        "discharge_c_rate": 1.5,
        "charge_c_rate": 1.0,
        "ambient_temperature_C": 45,
    }
)

print(f"Stopped at cycle {result['summary']['num_cycles_completed']}")
print(f"Reason: {result['stop_reason']}")
print(f"SoH: {result['summary']['final_soh_pct']:.2f}%")
```

### Example 3: Fast mode (200 cycles per step)

```python
result = run_cycle_degradation_multistep(
    cell_design,
    {"num_cycles": 1000, ...},
    cycles_per_step=200  # 5 steps total, ~75 min
)
```

---

## Need More Info?

📖 **Full Guide:** `MULTI_STEP_CYCLING_GUIDE.md`  
🔬 **Implementation:** `IMPLEMENTATION_SUMMARY_MULTISTEP.md`  
📓 **Example Notebook:** `notebooks/simulate_cycle_degradation.ipynb`

