# SPMeT Module Comparison

## Overview
All `spmet_*.py` modules implement PyBaMM-based battery simulations using the Single Particle Model with electrolyte (SPMeT). Key differences are in their scope and use cases.

| Module | Lines | Purpose | Main Function | Key Feature |
|--------|-------|---------|---------------|----|
| **spmet_drive.py** | 1076 | Drive cycle analysis | `run_drive_cycle()` | Full range/energy analysis with speed estimation |
| **spmet_bess.py** | 828 | Energy storage system | `run_duty_cycle()` | Duty cycle simulation for stationary storage |
| **spmet_dcir.py** | 836 | DCIR measurement | `simulate_dcir()` | Direct Current Internal Resistance at specific time points |
| **spmet_custom.py** | 886 | Custom experiments | `run_spmet()` | Flexible experiment definition with OCP data |
| **spmet_drive_bev_canvas.py** | 575 | BEV canvas (simplified) | `run_drive_cycle()` | Canvas component for BEV simulation |
| **spmet_drive_drone_canvas.py** | 529 | Drone canvas (simplified) | `run_drive_cycle()` | Canvas component for UAV simulation |

---

## Detailed Comparison

### 1. Parameter Building Strategy

#### **spmet_drive.py** & **spmet_bess.py**
- Use `_build_pybamm_params(cell_design, simulation_config)` helper
- Expect `cell_volume` to exist in cell_design
- Return tuple: `(calibrated_params, model_options)`

```python
"Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
```

#### **spmet_dcir.py** ⭐ **MOST ROBUST**
- Inline parameter building in `simulate_dcir()` function
- **Handles missing cell_volume** by calculating from dimensions
- Falls back to `cell_dimensions` if `cell_volume` not available
- Reads separator density from manifest (not hardcoded)

```python
if "cell_volume" in cell_design:
    cell_vol_m3 = cell_design["cell_volume"]["value"] / 1000.0
else:
    # Calculate from cell_dimensions
    dims = cell_design.get("cell_dimensions", {})
    h_mm = dims.get("height", {}).get("value", 82.0)
    w_mm = dims.get("width", {}).get("value", 280.0)
    t_mm = dims.get("thickness", {}).get("value", 63.0)
    cell_vol_m3 = (h_mm * w_mm * t_mm) / 1e9
```

#### **spmet_custom.py**
- Uses object-oriented access: `cell_design.cell_volume.value`
- Requires cell_volume to be present

---

### 2. Separator Density Handling

| Module | Approach |
|--------|----------|
| **spmet_drive.py** | Hardcoded: `"Separator density [kg.m-3]": 1000` |
| **spmet_bess.py** | Hardcoded: `"Separator density [kg.m-3]": 1000` |
| **spmet_dcir.py** ⭐ | Reads from manifest: `separator["material"]["density"]["value"] * 1000` |
| **Canvas versions** | Hardcoded: `1000` |

---

### 3. Capacity Calibration

All modules perform capacity calibration using the same approach:

```python
# Load default parameter set based on cathode chemistry
if "LFP" in cathode_material:
    default_params = pybamm.ParameterValues("Prada2013")
else:
    default_params = pybamm.ParameterValues("ORegan2022")

# Run charge/hold/discharge cycle with convergence tolerance
# Adjust electrode width until capacity matches target
```

**Calibration parameters:**
- `MAX_ITERATIONS: 20`
- `TOLERANCE: 0.0001` (0.01%)

---

### 4. DCIR Time Points

| Module | Time Points |
|--------|------------|
| **spmet_dcir.py** | `[0.1, 1.0, 10.0, 18.0, 30.0]` seconds |
| **simulate_dcir_canvas.py** | `[0.1, 1.0, 10.0, 18.0, 30.0]` seconds |

---

### 5. Return Value Structure

#### **spmet_dcir.py** (Single Point)
```python
{
    "success": True/False,
    "dcir_mOhm": {0.1: 1.23, 1.0: 1.45, ...},
    "conditions": {
        "initial_soc": 0.5,
        "temperature_K": 298.15,
        "temperature_C": 25.0,
        "c_rate": 1.0,
        "contact_resistance_Ohm": 1e-5
    },
    "error": "message" (optional)
}
```

#### **spmet_dcir.py** (Sweep)
```python
{
    "success": True/False,
    "surface_data": [
        {
            "soc": 0.5,
            "temperature_K": 298.15,
            "c_rate": 1.0,
            "dcir_mOhm": {0.1: 1.23, ...},
            "success": True/False
        },
        ...
    ],
    "sweep_params": {
        "soc_values": [...],
        "temperature_K_values": [...],
        "c_rate_values": [...]
    },
    "num_simulations": 27
}
```

#### **spmet_drive.py**
```python
{
    "success": True/False,
    "simulation_time_s": [...],
    "current_A": [...],
    "voltage_V": [...],
    "power_W": [...],
    "energy_Wh": float,
    "range_km": float,
    "efficiency_Wh_km": float,
    "average_power_W": float,
    "error": "message" (optional)
}
```

---

### 6. Key Strengths

| Module | Strength |
|--------|----------|
| **spmet_drive.py** | Complete drive cycle analysis, efficiency calculations, range estimation |
| **spmet_bess.py** | Stationary battery system simulation, duty cycle support |
| **spmet_dcir.py** ⭐ | Robust parameter handling, manifests reading, sweep capability |
| **spmet_custom.py** | Flexible experiment definition, custom OCP data loading |

---

### 7. Recommended Usage

- **DCIR Analysis**: Use `spmet_dcir.simulate_dcir()` ✅
- **Drive Cycles**: Use `spmet_drive.run_drive_cycle()`
- **BESS/Stationary**: Use `spmet_bess.run_duty_cycle()`
- **Custom Tests**: Use `spmet_custom.run_spmet()`
- **Canvas Components**: Use canvas versions for rapid prototyping

---

## Best Practices

1. **Always check for missing keys** in cell_design (like `cell_volume`)
2. **Read from manifest** rather than hardcoding values (separator density, etc.)
3. **Provide fallback values** for optional parameters
4. **Use manifest-based geometry** when cell_volume not available
5. **Maintain consistency** across modules for reproducibility

