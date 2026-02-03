# DFN Calendar Degradation Module

Created: February 3, 2026

## Overview

The `dfn_calendar_degradation` module simulates storage-induced (calendar) aging of Li-ion battery cells using the Doyle-Fuller-Newman (DFN) electrochemical model with coupled degradation mechanisms.

**Base Reference:** https://github.com/pybamm-team/PyBaMM/blob/main/examples/scripts/calendar_ageing.py

## Key Features

- **Full DFN Model**: Accounts for concentration gradients, current distribution, and electrochemical reactions
- **Degradation Mechanisms**:
  - SEI growth (solvent-diffusion limited) on negative electrode
  - Loss of lithium inventory (LLI) from side reactions
  - Loss of active material (LAM) from mechanical stress and cracking
  - Particle swelling and cracking
  - Electrode porosity evolution
- **Temperature Dependence**: Arrhenius-type models for degradation kinetics
- **Comprehensive Output**: Tracks capacity fade, voltage evolution, and degradation mechanisms

## Module Structure

### Main Function

```python
run_calendar_degradation(cell_design: Dict, sim_config: Dict) -> Dict[str, Any]
```

### Configuration Parameters

#### Required:
- `cell_design`: Cell design dictionary from manifest JSON
  - Contains electrode, separator, electrolyte specifications
  - Includes thermal and geometric properties

#### Optional (with defaults):
- `calendar_time_days`: Storage duration (default: 365 days)
- `initial_soc`: Initial state-of-charge (default: 0.8, range: 0-1)
- `ambient_temperature_C`: Storage temperature (default: 25°C)
- `upper_voltage_cutoff_V`: Maximum voltage (default: from manifest)
- `lower_voltage_cutoff_V`: Minimum voltage (default: from manifest)
- `contact_resistance_Ohm`: Electrical contact resistance (default: 0.0001 Ω)
- `total_heat_transfer_coefficient_W_m2K`: Heat transfer coefficient (default: 10 W/m²K)
- `cooling_surface_area_m2`: Thermal coupling area (default: 0.01 m²)
- `solver_atol`: Absolute tolerance for solver (default: 1e-4)
- `solver_rtol`: Relative tolerance for solver (default: 1e-4)

#### Degradation Parameters (with O'Kane2022 defaults):
- `initial_sei_thickness_m`: Initial SEI layer thickness (default: 5 nm)
- `sei_resistivity_Ohm_m`: SEI electrical resistivity (default: 2.5e5 Ω·m)
- `sei_growth_activation_energy_J_mol`: SEI formation activation energy (default: 50 kJ/mol)
- `negative_electrode_youngs_modulus_Pa`: Mechanical stiffness (default: 15 GPa)
- `positive_electrode_youngs_modulus_Pa`: NMC stiffness (default: 375 GPa)
- And many others... (see source file for complete list)

### Return Value

Dictionary with keys:
- `success`: Boolean indicating simulation success
- `error`: Error message if failed
- `data`: Timeseries arrays
  - `time_s`: Time [seconds]
  - `voltage_V`: Terminal voltage [V]
  - `temperature_K`: Cell temperature [K]
  - `capacity_Ah`: Dischargeable capacity [Ah]
  - `soc`: State of charge
  - `LLI_pct`: Loss of lithium inventory [%]
  - `LAM_neg_pct`: Loss of active material in negative electrode [%]
  - `LAM_pos_pct`: Loss of active material in positive electrode [%]
  - `Q_SEI_Ah`: Capacity lost to SEI [Ah]
  - `Q_SEI_cracks_Ah`: Capacity lost to SEI on cracks [Ah]
  - `Q_side_reactions_Ah`: Total capacity loss [Ah]
  - `porosity_neg`: Negative electrode porosity
  - `porosity_pos`: Positive electrode porosity
  - `throughput_Ah`: Charge throughput [Ah]
- `summary`: Aggregated degradation summary
  - `capacity_fade_Ah`: Total capacity loss [Ah]
  - `capacity_fade_pct`: Relative capacity loss [%]
  - `final_soh_pct`: Final state of health [%]
  - `LLI_pct`: Loss of lithium inventory [%]
  - `LAM_neg_pct`: Loss of active material (negative) [%]
  - `LAM_pos_pct`: Loss of active material (positive) [%]
  - `Q_SEI_total_Ah`: Total SEI-induced capacity loss [Ah]
  - `porosity_neg_change`: Change in negative electrode porosity
  - `porosity_pos_change`: Change in positive electrode porosity
- `config`: Copy of input simulation configuration

## Usage Example

```python
import json
from pathlib import Path
from model_library import run_calendar_degradation

# Load cell design
manifest_path = Path("cells/Tesla_Model3_Prismatic_160Ah_manifest.json")
with open(manifest_path) as f:
    manifest = json.load(f)
cell_design = manifest["cell_design"]

# Configure simulation
sim_config = {
    "calendar_time_days": 365,
    "initial_soc": 0.8,
    "ambient_temperature_C": 25,
}

# Run simulation
result = run_calendar_degradation(cell_design, sim_config)

if result["success"]:
    summary = result["summary"]
    print(f"Capacity fade: {summary['capacity_fade_pct']:.2f}%")
    print(f"LLI: {summary['LLI_pct']:.4f}%")
else:
    print(f"Error: {result['error']}")
```

## Test Notebook

**Location:** `notebooks/dfn_calendar_degradation.ipynb`

The test notebook includes:
1. Cell design loading from manifests
2. Basic calendar degradation simulation (25°C, 1 year, 80% SoC)
3. Results visualization (voltage, temperature, LLI/LAM, SEI evolution)
4. Temperature dependence study
5. State-of-charge dependence study
6. Summary statistics table
7. Performance notes and validation information

### Running the Notebook

```bash
cd /Users/manik/Github/model_library
jupyter notebook notebooks/dfn_calendar_degradation.ipynb
```

## Physical Interpretation

### Loss of Lithium Inventory (LLI)
- Represents capacity fade due to lithium consumption in side reactions
- Dominated by SEI growth (fastest degradation mechanism)
- Temperature and SoC dependent
- Typically 0.001-0.1% per year at room temperature

### Loss of Active Material (LAM)
- Capacity fade from mechanical degradation (particle cracking, disconnection)
- Stress-driven model based on volume changes
- More significant at higher temperatures and higher SoC
- Typically 0.001-0.01% per year at room temperature

### SEI Growth
- Initial layer formation dominates early-time degradation
- Later-time dominated by solvent diffusion through SEI
- Activation energy ~50 kJ/mol (typical for SEI formation)
- Increases resistance and reduces lithium transport

## Performance Notes

- **Typical Execution Time**: 2-5 minutes per year of simulated storage
- **Memory Usage**: 2-4 GB
- **Solver**: IDAKLUSolver with adaptive time-stepping
- **Mesh Resolution**: x_n=x_s=x_p=10, r_n=r_p=30 (standard)
  - Increase r_n, r_p for finer particle discretization
  - Increase x_* for finer spatial resolution in electrodes

## Model Validation

The module uses PyBaMM's O'Kane2022 parameter set with:
- SEI reaction mechanism: solvent-diffusion limited
- Particle mechanics: swelling and cracking
- LAM model: stress-driven with Paris' law crack propagation
- All parameters physically consistent with battery literature

## References

- **PyBaMM Documentation**: https://pybamm.readthedocs.io/
- **Calendar Aging Example**: https://github.com/pybamm-team/PyBaMM/blob/main/examples/scripts/calendar_ageing.py
- **O'Kane et al. (2022)**: "Lithium-ion battery degradation models based on physics and machine learning"
- **SEI Literature**: Various papers on solid-electrolyte interface growth kinetics

## Limitations & Future Work

### Current Limitations:
- No gas generation modeling (H₂, CO₂)
- No explicit lithium plating (set to "none" in calendar aging)
- Assumes constant ambient temperature
- Single cell simulation only (no pack effects)

### Potential Enhancements:
- Multi-layer SEI with different growth kinetics
- Lithium plating during rest at low potentials
- Coupled thermal-electrochemical model with transients
- Pack-level simulations with cell balancing
- Machine learning surrogate models for faster predictions

## Integration with Model Library

The module is integrated into the main `model_library` package:

```python
from model_library import run_calendar_degradation
```

It complements existing functions:
- `run_drive_cycle_with_degradation()`: Cycle aging simulation
- `run_drive_cycle()`: Drive cycle without degradation
- `run_spmet()`: SPMeT model for various operations
- `run_eis()`: Electrochemical impedance spectroscopy

All functions follow consistent patterns for parameter input and output formatting.
