# Capacity Calibration in DFN Degradation Models

## Why Capacity Calibration is Critical

### The Problem

The PyBaMM O'Kane2022 parameter set is based on specific electrode dimensions, active material loadings, and electrolyte properties that result in a **theoretical capacity of ~5 Ah**. However, real cells can have vastly different capacities:

- Tesla Model 3: **160 Ah**
- BYD Blade: **135 Ah**  
- VW ID.3: **80 Ah**

**Without calibration**, the DFN model will simulate a ~5 Ah cell, not your actual cell!

### The Impact

When capacity is not calibrated:

1. **Wrong baseline capacity**: All degradation calculations start from wrong value
2. **Incorrect SoH**: State of Health % will be meaningless
3. **Wrong C-rates**: A 1C discharge means 5A instead of 160A
4. **Invalid degradation metrics**: Capacity fade will be in wrong units
5. **Unusable predictions**: Results cannot be compared to real cells

### Example Without Calibration

```python
# Tesla Model 3 cell design: 160 Ah nominal
sim_config = {
    "num_cycles": 100,
    "discharge_c_rate": 1.0,  # User expects 160A
    "skip_capacity_calibration": True  # WRONG!
}

result = run_cycle_degradation(cell_design, sim_config)
# Result: Model simulates ~5 Ah cell at ~5A discharge rate
# SoH drops from 100% to 95% means 5 Ah → 4.75 Ah (0.25 Ah fade)
# But user expects 160 Ah → 152 Ah (8 Ah fade)
# Results are OFF BY 32x!
```

### Example With Calibration (Correct)

```python
# Tesla Model 3 cell design: 160 Ah nominal
sim_config = {
    "num_cycles": 100,
    "discharge_c_rate": 1.0,  # Will be 160A
    "skip_capacity_calibration": False  # DEFAULT - correct!
}

result = run_cycle_degradation(cell_design, sim_config)
# Result: Model simulates 160 Ah cell at 160A discharge rate
# SoH drops from 100% to 95% means 160 Ah → 152 Ah (8 Ah fade)
# Results match real cell behavior!
```

## How Calibration Works

### The Algorithm

1. **Run a slow charge-discharge test** (C/10 rate)
   - Charge at 0.1C to upper voltage cutoff
   - Hold at upper voltage until current drops
   - Discharge at 0.1C to lower voltage cutoff

2. **Measure actual capacity** from discharge curve

3. **Calculate scale factor**:
   ```
   scale_factor = measured_capacity / target_capacity
   ```

4. **Adjust electrode width** proportionally:
   ```
   new_width = current_width / scale_factor
   ```
   
   This physically changes the electrode area, which directly affects capacity

5. **Iterate** until convergence (typically 3-8 iterations)

### Why Electrode Width?

The cell capacity depends on:
- Active material mass = electrode_area × thickness × loading × density
- Electrode area = width × height

By adjusting **width**, we scale the electrode area proportionally, which scales the capacity without affecting:
- Material properties (OCV curves, diffusivities, conductivities)
- Electrode thickness and porosity
- Particle size distributions
- Kinetic parameters

### Convergence

The calibration uses a **0.01% tolerance** (TOLERANCE = 0.0001):

```
Target: 160.00 Ah
Iteration  1: Capacity =   5.20 Ah, Error = 96.750%
Iteration  2: Capacity = 159.50 Ah, Error =  0.313%
Iteration  3: Capacity = 159.98 Ah, Error =  0.013%
Iteration  4: Capacity = 160.00 Ah, Error =  0.001%  ✓ Converged!
```

Typical convergence: **3-8 iterations**, taking ~2-5 minutes total.

## Performance Considerations

### Calibration Cost

- **Time**: 2-5 minutes (one-time cost per simulation)
- **Accuracy gain**: Orders of magnitude improvement
- **When to skip**: Only for debugging or parameter sensitivity studies

### When to Skip Calibration

```python
sim_config = {
    "skip_capacity_calibration": True  # Only use if:
    # 1. Debugging model setup issues
    # 2. Comparing PyBaMM parameter sets
    # 3. Running rapid prototyping tests
    # 4. Studying degradation mechanisms in isolation
}
```

**Always calibrate for production use!**

## Implementation Details

### Both Modules Include Calibration

✅ **dfn_cycle_degradation.py**: Calibrated capacity before cycling  
✅ **dfn_calendar_degradation.py**: Calibrated capacity before storage

### Calibration Updates

The calibration process also extracts and updates:

1. **Open-circuit voltage at 100% SoC** (OCV₁₀₀)
2. **Open-circuit voltage at 0% SoC** (OCV₀)

These are measured from the actual charge-discharge curves and ensure the voltage range matches the cell design.

### Code Structure

```python
def calibrate_capacity(
    cell_design: Dict,
    param: pybamm.ParameterValues,
    model_options: Dict[str, str],
) -> Tuple[pybamm.ParameterValues, bool]:
    """
    Returns:
        (calibrated_params, success_flag)
    """
    # ... iterative calibration logic ...
    param.update({
        "Electrode width [m]": new_width,
        "Open-circuit voltage at 100% SOC [V]": ocv_100,
        "Open-circuit voltage at 0% SOC [V]": ocv_0,
    })
    return param, True
```

### Integration

Both modules call calibration automatically:

```python
def run_cycle_degradation(cell_design, sim_config):
    # Build parameters
    param = build_dfn_cycle_degradation_params(...)
    
    # Capacity calibration (unless skipped)
    if not sim_config.get("skip_capacity_calibration", False):
        param, success = calibrate_capacity(...)
        if not success:
            print("⚠ Warning: Calibration did not fully converge")
    
    # Continue with simulation...
```

## Verification

### Check Calibration Worked

After simulation, verify the initial capacity matches:

```python
result = run_cycle_degradation(cell_design, sim_config)

if result["success"]:
    initial_cap = result["summary"]["initial_capacity_Ah"]
    target_cap = cell_design["nominal_capacity"]["value"]
    
    error_pct = abs(initial_cap - target_cap) / target_cap * 100
    
    if error_pct < 0.1:  # Less than 0.1% error
        print(f"✓ Calibration verified: {initial_cap:.2f} Ah")
    else:
        print(f"⚠ Warning: Capacity mismatch {error_pct:.2f}%")
```

### Expected Output

With calibration enabled (default):

```
================================================================================
CAPACITY CALIBRATION
================================================================================
Target capacity: 160.00 Ah
Voltage range: 2.50V - 4.20V
Convergence tolerance: 0.010%
--------------------------------------------------------------------------------
Iteration  1: Capacity =   5.23 Ah, Error = 96.731%
Iteration  2: Capacity = 159.82 Ah, Error =  0.113%
Iteration  3: Capacity = 159.99 Ah, Error =  0.006%
--------------------------------------------------------------------------------
✓ Converged after 3 iterations!
  Final capacity: 159.99 Ah
  Target capacity: 160.00 Ah
  Error: 0.006%
  OCV at 100% SoC: 4.198V
  OCV at 0% SoC: 2.513V
================================================================================
```

## Summary

### Critical Points

1. **Always calibrate for production** - Default behavior is correct
2. **Calibration is automatic** - No user action needed
3. **Cost is minimal** - 2-5 minutes one-time cost
4. **Accuracy is essential** - Orders of magnitude improvement
5. **Skip only for debugging** - Not for real predictions

### Default Behavior

```python
# ✓ CORRECT - Uses calibration by default
result = run_cycle_degradation(cell_design, sim_config)

# ✓ EXPLICIT - Same as above
sim_config["skip_capacity_calibration"] = False
result = run_cycle_degradation(cell_design, sim_config)

# ⚠ DANGEROUS - Only for debugging
sim_config["skip_capacity_calibration"] = True
result = run_cycle_degradation(cell_design, sim_config)
```

### Questions?

**Q: Why not just set "Nominal cell capacity [A.h]" directly?**  
A: That parameter is metadata. The actual capacity comes from electrode dimensions and material properties. We must adjust those physical parameters.

**Q: Does calibration change degradation behavior?**  
A: No. It only scales the electrode area. Degradation mechanisms (SEI growth rate, LAM kinetics, etc.) remain unchanged and scale proportionally with the larger electrode.

**Q: Can I compare cells with different capacities?**  
A: Yes! After calibration, each cell simulates its own capacity correctly. Compare percentage metrics (SoH%, capacity fade%) or normalize by C-rate.

**Q: What if calibration fails?**  
A: The function returns `success=False` and continues with best-fit parameters. You'll see a warning. Check cell design parameters and voltage cutoffs.

---

**Updated**: February 2026  
**Applies to**: `dfn_cycle_degradation.py` v2.0+, `dfn_calendar_degradation.py` v2.0+
