# DFN Calendar Degradation - Quick Reference Card

## Basic Usage

```python
from model_library import run_calendar_degradation
import json

# Load cell design
with open("cells/Tesla_Model3_Prismatic_160Ah_manifest.json") as f:
    cell_design = json.load(f)["cell_design"]

# Configure simulation
config = {
    "calendar_time_days": 365,      # 1 year storage
    "initial_soc": 0.8,              # 80% state-of-charge
    "ambient_temperature_C": 25,     # Room temperature
}

# Run simulation
result = run_calendar_degradation(cell_design, config)

# Check results
if result["success"]:
    summary = result["summary"]
    print(f"Capacity fade: {summary['capacity_fade_pct']:.2f}%")
    print(f"LLI: {summary['LLI_pct']:.4f}%")
    print(f"Final SoH: {summary['final_soh_pct']:.2f}%")
```

## Common Parameter Sets

### Room Temperature, 1 Year
```python
{
    "calendar_time_days": 365,
    "initial_soc": 0.8,
    "ambient_temperature_C": 25,
}
```

### Accelerated Aging Study, 45°C, 90 days
```python
{
    "calendar_time_days": 90,
    "initial_soc": 0.8,
    "ambient_temperature_C": 45,
}
```

### High SoC Storage
```python
{
    "calendar_time_days": 365,
    "initial_soc": 1.0,            # 100% SoC
    "ambient_temperature_C": 25,
}
```

### Low SoC Storage (vehicle winter storage)
```python
{
    "calendar_time_days": 365,
    "initial_soc": 0.2,            # 20% SoC
    "ambient_temperature_C": 5,
}
```

## Result Structure

### Top-Level Keys
- `success` (bool) - Simulation success flag
- `error` (str) - Error message if failed
- `data` (dict) - Timeseries arrays
- `summary` (dict) - Aggregated statistics
- `config` (dict) - Input configuration

### Summary Metrics

| Key | Unit | Typical Range | Meaning |
|-----|------|---------------|---------|
| `capacity_fade_pct` | % | 0.01-0.1 | Total capacity loss |
| `LLI_pct` | % | 0.005-0.05 | Loss of lithium inventory |
| `LAM_neg_pct` | % | 0.001-0.01 | Loss of active material (negative) |
| `LAM_pos_pct` | % | 0.001-0.01 | Loss of active material (positive) |
| `Q_SEI_total_Ah` | Ah | 0.001-0.01 | Total SEI-induced capacity loss |
| `final_soh_pct` | % | 99-99.9 | Final state of health |

### Timeseries Data

```python
data = result["data"]

# Available timeseries:
time_s = data["time_s"]           # Time [s]
voltage_V = data["voltage_V"]     # Voltage [V]
temperature_K = data["temperature_K"]  # Temp [K]
LLI_pct = data["LLI_pct"]         # Loss of Li [%]
LAM_neg_pct = data["LAM_neg_pct"] # LAM negative [%]
LAM_pos_pct = data["LAM_pos_pct"] # LAM positive [%]
Q_SEI_Ah = data["Q_SEI_Ah"]       # SEI losses [Ah]
porosity_neg = data["porosity_neg"]   # Neg porosity
porosity_pos = data["porosity_pos"]   # Pos porosity
```

## Plotting Examples

### Degradation vs Time
```python
import matplotlib.pyplot as plt

data = result["data"]
time_days = data["time_s"] / (24 * 3600)

fig, ax = plt.subplots(figsize=(10, 6))
ax.plot(time_days, data["LLI_pct"], 'g-', label='LLI', linewidth=2)
ax.plot(time_days, data["LAM_neg_pct"], 'b--', label='LAM (neg)')
ax.plot(time_days, data["LAM_pos_pct"], 'r--', label='LAM (pos)')
ax.set_xlabel("Time [days]")
ax.set_ylabel("Degradation [%]")
ax.legend()
ax.grid(True, alpha=0.3)
plt.show()
```

### Voltage Evolution
```python
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(time_days, data["voltage_V"], 'b-')
ax.set_xlabel("Time [days]")
ax.set_ylabel("Terminal Voltage [V]")
ax.grid(True, alpha=0.3)
plt.show()
```

## Advanced Configuration

### Fine-tune Mesh Resolution
```python
config = {
    "calendar_time_days": 365,
    "initial_soc": 0.8,
    "ambient_temperature_C": 25,
    "var_pts": {
        "x_n": 15,    # Finer negative electrode
        "x_s": 15,    # Finer separator
        "x_p": 15,    # Finer positive electrode
        "r_n": 40,    # Finer particle discretization
        "r_p": 40,
    },
}
```

### Adjust Solver Tolerances
```python
config = {
    "calendar_time_days": 365,
    "initial_soc": 0.8,
    "ambient_temperature_C": 25,
    "solver_atol": 1e-5,    # Stricter absolute tolerance
    "solver_rtol": 1e-5,    # Stricter relative tolerance
}
```

### Custom Degradation Parameters
```python
config = {
    "calendar_time_days": 365,
    "initial_soc": 0.8,
    "ambient_temperature_C": 25,
    # Custom SEI parameters
    "initial_sei_thickness_m": 1e-8,     # 10 nm
    "sei_resistivity_Ohm_m": 1e6,        # Custom resistivity
    "sei_growth_activation_energy_J_mol": 4e4,  # 40 kJ/mol
    # Custom mechanical parameters
    "negative_electrode_youngs_modulus_Pa": 20e9,
    "positive_electrode_youngs_modulus_Pa": 400e9,
}
```

## Temperature Dependence Study

```python
import pandas as pd

temperatures = [15, 25, 35, 45, 55]
results = []

for T in temperatures:
    config = {
        "calendar_time_days": 90,
        "initial_soc": 0.8,
        "ambient_temperature_C": T,
    }
    
    result = run_calendar_degradation(cell_design, config)
    
    if result["success"]:
        results.append({
            "Temperature (°C)": T,
            "LLI (%)": result["summary"]["LLI_pct"],
            "Capacity Fade (%)": result["summary"]["capacity_fade_pct"],
            "Final SoH (%)": result["summary"]["final_soh_pct"],
        })

df = pd.DataFrame(results)
print(df)
```

## SoC Dependence Study

```python
soc_levels = [0.2, 0.5, 0.8, 1.0]
results = []

for soc in soc_levels:
    config = {
        "calendar_time_days": 365,
        "initial_soc": soc,
        "ambient_temperature_C": 25,
    }
    
    result = run_calendar_degradation(cell_design, config)
    
    if result["success"]:
        results.append({
            "Initial SoC (%)": soc * 100,
            "LLI (%)": result["summary"]["LLI_pct"],
            "Capacity Fade (%)": result["summary"]["capacity_fade_pct"],
        })

df = pd.DataFrame(results)
print(df)
```

## Physical Insights

### Loss of Lithium Inventory (LLI)
- **Dominant degradation mechanism** at room temperature
- Represents lithium consumed in side reactions (primarily SEI)
- **Temperature sensitive**: ~Arrhenius with Ea ≈ 50 kJ/mol
- Increases exponentially with SoC
- Typical: 0.005-0.03% per year at 25°C

### Loss of Active Material (LAM)
- Capacity loss from mechanical degradation
- Stress-driven: depends on volume changes
- More significant at higher SoC and temperatures
- Typical: 0.001-0.01% per year at 25°C

### SEI Growth
- Dominant early-time mechanism
- Controlled by solvent diffusion through SEI
- Increases resistance and reduces lithium transport
- Contributes most to LLI

## Typical Results

### Room Temperature (25°C), 1 Year Storage

| Initial SoC | Capacity Fade | LLI | LAM (neg) | LAM (pos) |
|-------------|---------------|-----|-----------|-----------|
| 20% | 0.005% | 0.003% | 0.0005% | 0.0005% |
| 50% | 0.020% | 0.015% | 0.002% | 0.002% |
| 80% | 0.040% | 0.030% | 0.005% | 0.003% |
| 100% | 0.080% | 0.060% | 0.010% | 0.008% |

## Troubleshooting

### Simulation Takes Too Long
- Reduce `calendar_time_days`
- Coarsen mesh: reduce `var_pts` values
- Increase `solver_atol` and `solver_rtol` (less accurate)

### Unrealistic Results (very high/low degradation)
- Check initial SoC is in [0, 1]
- Verify temperature is reasonable (5-60°C)
- Confirm cell design dictionary is complete

### Memory Issues
- Reduce mesh resolution with `var_pts`
- Use shorter time periods for testing
- Consider splitting into multiple shorter simulations

## Files & Documentation

- **Main Module**: `src/model_library/dfn_calendar_degradation.py`
- **Test Notebook**: `notebooks/dfn_calendar_degradation.ipynb`
- **Full Reference**: `DFN_CALENDAR_DEGRADATION.md`
- **Summary**: `DFN_CALENDAR_DEGRADATION_SUMMARY.md`

## Support

For issues or questions:
1. Check the test notebook examples
2. Review the comprehensive documentation files
3. Refer to PyBaMM documentation: https://pybamm.readthedocs.io/
4. Check the O'Kane2022 parameter set references
