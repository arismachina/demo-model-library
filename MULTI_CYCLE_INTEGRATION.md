# Multi-Cycle Degradation Integration

## Summary

Successfully integrated multi-cycle degradation simulation into the `dfn_drive_degradation` module with a **unified configuration approach** where all parameters (degradation options, cycle limits, time limits, SoH threshold) are specified in a single `simulation_config` dictionary.

## Changes Made

### 1. Module Updates (`dfn_drive_degradation.py`)

#### New Functions Added:

**`run_multi_cycle_degradation()`**
- Runs multiple drive cycles until SoH threshold, cycle limit, or time limit
- Returns cycle history with per-cycle metrics
- Tracks: SoH, FCE, energy throughput, degradation modes, elapsed time
- Parameters:
  - `cell_design`: Cell design dict
  - `simulation_config`: Degradation configuration
  - `soh_threshold`: Stop when SoH < this (default: 80.0%)
  - `max_cycles`: Maximum cycles (default: 1000)
  - `max_simulation_time_s`: Wall-clock time limit (default: None)
  - `save_interval`: Progress print interval (default: 10)

**`print_multi_cycle_summary()`**
- Formatted summary report for multi-cycle results
- Displays: cycles, SoH, FCE, energy throughput, degradation mechanisms
- Includes stop reason and performance metrics

### 2. Module Exports (`__init__.py`)

Added to `__all__`:
- `run_multi_cycle_degradation`
- `print_multi_cycle_summary`

### 3. Notebook Updates (`simulate_drive_cycle_degradation.ipynb`)

#### Updated Imports (Cell 2):
```python
from model_library import (
    run_drive_cycle_with_degradation,
    print_drive_cycle_degradation_report,
    run_multi_cycle_degradation,      # NEW
    print_multi_cycle_summary,         # NEW
)
```

#### Section 4 Enhancement:
- Added markdown cell explaining single vs multi-cycle time control

#### Section 10 Improvements:
- **Removed**: In-notebook function definition (moved to module)
- **Updated**: Multi-cycle execution to use module function
- **Added**: Time-controlled simulation examples
- **Enhanced**: Documentation with time control strategies

#### New Cells Added:
1. **Time Control Examples**: Markdown explaining time limits
2. **Configuration Examples**: 4 pre-configured time strategies:
   - `quick_test_config`: 10 cycles or 10 min
   - `one_hour_config`: Up to 100 cycles in 1 hour
   - `two_hour_config`: Up to 200 cycles in 2 hours
   - `unlimited_config`: Run to completion (no time limit)
3. **Updated Summary**: Uses `print_multi_cycle_summary()` from module

## Time Control Features

### Single-Cycle Mode
- Time controlled by drive cycle duration (e.g., 60 min for WLTP)
- No explicit time limit parameter

### Multi-Cycle Mode
Three ways to control simulation duration:

1. **SoH Threshold** (default: 80%):
   ```python
   run_multi_cycle_degradation(..., soh_threshold=80.0)
   ```

2. **Cycle Limit**:
   ```python
   run_multi_cycle_degradation(..., max_cycles=100)
   ```

3. **Time Limit** (NEW):
   ```python
   run_multi_cycle_degradation(..., max_simulation_time_s=3600)  # 1 hour
   ```

**Priority**: Simulation stops when **any** condition is met (SoH < threshold, max_cycles, or time_limit)

## Usage Examples

### Quick Test (10 minutes)
```python
config = {
    **base_config,
    # Degradation options
    "sei_model": "solvent-diffusion limited",
    # Multi-cycle control (all in config)
    "soh_threshold": 80.0,
    "max_cycles": 10,
    "max_simulation_time_s": 600,  # 10 minutes
    "save_interval": 2,
}

result = run_multi_cycle_degradation(
    cell_design=cell_design,
    simulation_config=config,  # All parameters in config
)
print_multi_cycle_summary(result)
```

### Production Run (2 hours)
```python
config = {
    **base_config,
    # Full degradation
    "sei_model": "solvent-diffusion limited",
    "lithium_plating": "partially reversible",
    "particle_mechanics": ("swelling and cracking", "swelling only"),
    "sei_on_cracks": "true",
    "loss_of_active_material": "stress-driven",
    # Multi-cycle control
    "soh_threshold": 80.0,
    "max_cycles": 200,
    "max_simulation_time_s": 7200,  # 2 hours
    "save_interval": 10,
}

result = run_multi_cycle_degradation(
    cell_design=cell_design,
    simulation_config=config,
)
```

### Unlimited (Run to Completion)
```python
config = {
    **base_config,
    # SEI-only (fastest)
    "sei_model": "solvent-diffusion limited",
    # Multi-cycle control
    "soh_threshold": 80.0,
    "max_cycles": 1000,
    "max_simulation_time_s": None,  # No time limit
    "save_interval": 20,
}

result = run_multi_cycle_degradation(
    cell_design=cell_design,
    simulation_config=config,
)
```

## Output Structure

### `cycle_history` (Dict of Lists)
Per-cycle metrics for DataFrame creation:
- `cycle_number`: Cycle index
- `soh_pct`: State of Health (%)
- `capacity_Ah`: Remaining capacity (Ah)
- `fce`: Full Cycle Equivalent
- `energy_throughput_Wh`: Cumulative energy cycled (Wh)
- `total_throughput_Ah`: Cumulative charge throughput (Ah)
- `LLI_pct`, `LAM_neg_pct`, `LAM_pos_pct`: Degradation modes (%)
- `Q_SEI_Ah`, `Q_SEI_cracks_Ah`, `Q_plating_Ah`: Capacity losses (Ah)
- `porosity_neg`, `porosity_pos`: Electrode porosity
- `elapsed_time_s`: Cumulative wall-clock time (s)

### `summary` (Dict)
Aggregated statistics:
- `total_cycles`: Number of cycles completed
- `stop_reason`: Why simulation stopped ('soh_threshold', 'max_cycles', 'time_limit', 'error')
- `final_soh_pct`: Final State of Health (%)
- `total_fce`: Total Full Cycle Equivalent
- `total_energy_throughput_kWh`: Total energy cycled (kWh)
- `total_simulation_time_hr`: Total wall-clock time (hr)
- `degradation_mechanisms`: Active degradation models
- Performance metrics: cycles/energy/FCE per 1% SoH loss

## Stop Reasons

The simulation tracks why it stopped:
- **`soh_threshold`**: SoH dropped below target
- **`max_cycles`**: Reached cycle limit
- **`time_limit`**: Exceeded `max_simulation_time_s`
- **`error`**: Simulation failed

## Benefits

1. **Time Predictability**: Set wall-clock time limits for CI/CD, demos, or time-constrained testing
2. **Resource Management**: Prevent runaway simulations
3. **Flexible Testing**: Quick validation (10 min) vs production runs (hours)
4. **Module-Based**: Clean separation between notebook and reusable code
5. **Backward Compatible**: Existing single-cycle code unchanged

## Migration Notes

### Before (In-Notebook Function):
```python
# Function defined in notebook cell
def run_multi_cycle_until_soh_threshold(...):
    # 175 lines of code in notebook
    ...

# Call function
results = run_multi_cycle_until_soh_threshold(...)
```

### After (Module Function):
```python
# Import from module
from model_library import run_multi_cycle_degradation, print_multi_cycle_summary

# All parameters in simulation_config (unified approach)
config = {
    **base_config,
    # Degradation options
    "sei_model": "solvent-diffusion limited",
    "lithium_plating": "partially reversible",
    # Multi-cycle control (all in config)
    "soh_threshold": 80.0,
    "max_cycles": 100,
    "max_simulation_time_s": 3600,  # 1 hour time limit
    "save_interval": 5,
}

# Single function call with unified config
results = run_multi_cycle_degradation(
    cell_design=cell_design,
    simulation_config=config,  # All parameters here
)

# Print formatted summary
print_multi_cycle_summary(results)
```

## Testing

Verified module imports:
```bash
✓ Multi-cycle functions imported successfully!
✓ Functions available: run_multi_cycle_degradation, print_multi_cycle_summary
```

## Files Modified

1. `/src/model_library/dfn_drive_degradation.py` (+280 lines)
   - Added `run_multi_cycle_degradation()` function
   - Added `print_multi_cycle_summary()` function

2. `/src/model_library/__init__.py` (+2 exports)
   - Exported new multi-cycle functions

3. `/notebooks/simulate_drive_cycle_degradation.ipynb` (updated)
   - Updated imports
   - Removed in-notebook function definition
   - Added time control examples
   - Enhanced documentation
   - Added 3 new cells (time control configs)

## Future Enhancements

Potential additions:
1. Checkpointing: Save state every N cycles
2. Adaptive time limits: Adjust based on convergence
3. Parallel multi-cycle: Run multiple configs simultaneously
4. Real-time plotting: Update plots during long runs
5. Early stopping: Additional criteria (e.g., porosity threshold)

## Performance Notes

Typical cycle times (with SEI + Li plating):
- Cycle 1 (with calibration): ~3 min
- Cycles 2+: ~1-2 min

**Example timing**:
- 10 cycles: ~15-20 min
- 50 cycles: ~1.5 hr
- 100 cycles: ~3 hr

Use `max_simulation_time_s` to enforce hard limits regardless of cycle times.
