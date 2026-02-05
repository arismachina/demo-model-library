# Power Reduction Strategy: 10x Divisor for Infeasible Steps

## Problem
When PyBaMM reports "Step is infeasible at initial conditions" with `skip_ok=True`, it silently skips the step and returns a solution with only the REST cycle. The old algorithm didn't detect this and would either:
1. Try to extract data from the REST cycle only (crash)
2. Continue increasing power (wrong direction)

## Solution
**Detect skipped steps by checking actual power < 1W, then reduce power by 10x divisor**

### Detection Logic
```python
# Check if PyBaMM actually executed the power step
actual_power = float(data_source["Power [W]"].entries[-1])

# If power is near zero, the step was skipped (infeasible)
if abs(actual_power) < 1.0:
    # Step was infeasible - power demand too high
    if last_valid_power is not None:
        # We have valid powers, mark boundary
        first_invalid_power = current_power
        break
    else:
        # Haven't found any valid power yet - reduce aggressively
        current_power /= 10.0  # Divide by 10, not 1.2
        if current_power < min_power_floor:  # Stop at 50W
            break
        continue
```

### Why 10x vs 1.2x?
- **Coarse sweep multiplier (1.2x)**: Increases power 20% per step searching upward
- **Power reduction divisor (10x)**: Divides power when infeasible to quickly escape bad region
- **Asymmetry is intentional**: Slow climb up, fast drop down

### Example: 80% SOC, 1s Charge Pulse at 5°C
All power levels from 100W down are infeasible (voltage window too tight):
```
100W    → infeasible, divide by 10 → 10W
10W     → still infeasible, but below 50W floor → STOP
Result: 0.0W (correctly identifies no feasible charge power exists)
```

### Applied in Two Places
1. **Coarse Sweep** (lines ~365): Initial search for valid power range
2. **Binary Search** (lines ~482): Refining between valid/invalid boundaries

## Outcome
- Infeasible operating points now return 0.0W (correct)
- Algorithm doesn't waste time on impossibly high power levels
- Physically meaningful results: "This operation cannot be safely performed"
