"""
Standalone DCIR Simulation Module using SPMeT

This module provides a complete standalone interface for calculating DCIR (Direct Current
Internal Resistance) at specific time points (0.1s, 1s, 10s, 18s, 30s) from cell design parameters.

Supports both single-point and sweep simulations across SOC, temperature, and C-rate arrays.

Default conditions: 50% SOC, 25°C (298.15K)
"""

import pybamm
import numpy as np
from typing import Union, List


def _build_pybamm_params(
    cell_design: dict,
    simulation_config: dict,
) -> tuple[pybamm.ParameterValues, dict]:
    """
    Build PyBaMM parameters from cell design manifest.

    Args:
        cell_design: Cell design parameters dictionary
        simulation_config: Simulation configuration dictionary

    Returns:
        Tuple of (parameter_values, model_options)
    """
    default_params = pybamm.ParameterValues({})

    print("\nBuilding model parameters from manifest...")

    if (
        cell_design["positive_electrode"]["coating"]["formulation"][
            "primary_active_material"
        ]["name"]
        == "LFP"
    ):
        default_params = pybamm.ParameterValues("Prada2013")
    else:
        default_params = pybamm.ParameterValues("ORegan2022")

    # Cell parameters
    cell_params = {
        "Nominal cell capacity [A.h]": cell_design["nominal_capacity"]["value"],
    }

    # Positive electrode parameters
    number_of_coated_sides = 2
    pos_electrode = cell_design["positive_electrode"]

    positive_electrode_params = {
        "Number of electrodes connected in parallel to make a cell": (
            pos_electrode["count"]["value"]
            * cell_design["jelly_roll"]["count"]["value"]
            * number_of_coated_sides
        ),
        "Electrode height [m]": pos_electrode["height"]["value"] / 1000,
        "Electrode width [m]": pos_electrode["width"]["value"] / 1000,
        "Electrode length [m]": pos_electrode["width"]["value"] / 1000,
        "Positive electrode thickness [m]": pos_electrode["coating"]["thickness"][
            "value"
        ]
        / 1e6,
        "Positive electrode porosity": pos_electrode["coating"]["porosity"]["value"],
        "Positive electrode active material volume fraction": pos_electrode["coating"][
            "active_material_volume_fraction"
        ]["value"],
        "Positive electrode density [kg.m-3]": pos_electrode["coating"]["density"][
            "value"
        ]
        * 1000,
    }

    positive_cc_params = {
        "Positive current collector thickness [m]": pos_electrode["foil"]["thickness"][
            "value"
        ]
        / 1e6,
    }

    # Negative electrode parameters
    neg_electrode = cell_design["negative_electrode"]

    negative_electrode_params = {
        "Negative electrode thickness [m]": neg_electrode["coating"]["thickness"][
            "value"
        ]
        / 1e6,
        "Negative electrode porosity": neg_electrode["coating"]["porosity"]["value"],
        "Negative electrode active material volume fraction": neg_electrode["coating"][
            "active_material_volume_fraction"
        ]["value"],
        "Negative electrode density [kg.m-3]": neg_electrode["coating"]["density"][
            "value"
        ]
        * 1000,
    }

    negative_cc_params = {
        "Negative current collector thickness [m]": neg_electrode["foil"]["thickness"][
            "value"
        ]
        / 1e6,
    }

    # Separator parameters
    separator = cell_design["separator"]
    separator_params = {
        "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
        "Separator porosity": separator["porosity"]["value"],
        "Separator density [kg.m-3]": separator["material"]["physical_properties"][
            "density"
        ]["value"]
        * 1000,
    }

    # Thermal parameters
    thermal_params = {
        "Reference temperature [K]": 298.15,
        "Total heat transfer coefficient [W.m-2.K-1]": simulation_config[
            "total_heat_transfer_coefficient"
        ],
        "Cell cooling surface area [m2]": simulation_config["cooling_surface_area"],
        "Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
    }

    # Operating conditions
    operating_conditions = {
        "Ambient temperature [K]": simulation_config["ambient_temperature"],
        "Initial temperature [K]": simulation_config["initial_temperature"],
        "Contact resistance [Ohm]": simulation_config["contact_resistance"],
        "Upper voltage cut-off [V]": simulation_config["upper_voltage_cutoff"],
        "Lower voltage cut-off [V]": simulation_config["lower_voltage_cutoff"],
    }

    # Combine all parameters
    pybamm_params = {
        **cell_params,
        **positive_electrode_params,
        **positive_cc_params,
        **negative_electrode_params,
        **negative_cc_params,
        **separator_params,
        **thermal_params,
        **operating_conditions,
    }

    default_params.update(pybamm_params, check_already_exists=False)

    # Set PyBaMM model options
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    # ========== CAPACITY CALIBRATION ==========
    target_capacity_Ah = cell_design["nominal_capacity"]["value"]

    charge_step = (
        f"Charge at 0.1C until {cell_design['upper_voltage_cutoff']['value']} V"
    )
    hold_step = f"Hold at {cell_design['upper_voltage_cutoff']['value']} V for 2 hours or until C/50"
    discharge_step = f"Discharge at 0.1C for 15 hours or until {cell_design['lower_voltage_cutoff']['value']} V"

    capacity_match_experiment = pybamm.Experiment(
        [
            (
                "Rest for 1 seconds",
                charge_step,
                hold_step,
            ),
            ("Rest for 3600 seconds",),
            (discharge_step,),
            ("Rest for 1 seconds",),
        ],
        period="1 second",
    )

    model_capacity = pybamm.lithium_ion.SPMe(options=model_options)

    MAX_ITERATIONS = 20
    TOLERANCE = 0.0001

    for iteration in range(MAX_ITERATIONS):
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=default_params,
        )

        try:
            sol_capacity = sim_capacity.solve(
                solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
            )
        except pybamm.SolverError as e:
            raise

        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            break

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah

        if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
            ocv_100 = float(sol_capacity.cycles[1]["Terminal voltage [V]"].entries[-1])
            ocv_0 = float(sol_capacity.cycles[3]["Terminal voltage [V]"].entries[-1])

            default_params.update(
                {
                    "Open-circuit voltage at 100% SOC [V]": ocv_100,
                    "Open-circuit voltage at 0% SOC [V]": ocv_0,
                },
                check_already_exists=False,
            )
            break

        new_width = default_params["Electrode width [m]"] / scale_factor
        default_params.update(
            {
                "Electrode width [m]": new_width,
                "Nominal cell capacity [A.h]": discharge_capacity / scale_factor,
            },
            check_already_exists=False,
        )

    return default_params, model_options


def run_spmet_dcir(
    cell_design: dict,
    kpis: dict,
    initial_soc: Union[float, List[float], np.ndarray] = 0.5,
    temperature_K: Union[float, List[float], np.ndarray] = 298.15,
    c_rate: Union[float, List[float], np.ndarray] = 1.0,
    contact_resistance: float = 1e-5,
) -> dict:
    """
    Simulate DCIR at specific time points (0.1s, 1s, 10s, 18s, 30s).

    This is a standalone function that takes cell design and kpis dicts and returns
    DCIR values at the specified time points. Supports both single-point and sweep
    simulations when arrays are provided for SOC, temperature, or C-rate.

    Args:
        cell_design: Cell design parameters dictionary
        kpis: KPIs dictionary containing nominal_capacity
        initial_soc: Initial state of charge [0-1] or array of SOC values (default: 0.5)
        temperature_K: Temperature [K] or array of temperatures (default: 298.15 = 25°C)
        c_rate: Pulse amplitude as C-rate or array of C-rates (default: 1.0)
        contact_resistance: Contact resistance [Ohm] (default: 1e-5)

    Returns:
        For single values: Dictionary containing:
            - success: Boolean indicating if simulation succeeded
            - dcir_mOhm: Dict mapping time points (s) to DCIR values (mOhm)
            - conditions: Dict with simulation conditions
            - error: Error message if failed (optional)

        For array inputs: Dictionary containing:
            - success: Boolean indicating if all simulations succeeded
            - surface_data: List of dicts, each with soc, temperature_K, temperature_C,
                           c_rate, dcir_mOhm (dict of time points to values)
            - sweep_params: Dict with soc_values, temperature_K_values, c_rate_values arrays
            - num_simulations: Total number of simulations run
            - error: Error message if failed (optional)

    Example (single point):
        >>> dcir_results = simulate_dcir(cell_design, kpis)
        >>> print(dcir_results["dcir_mOhm"])
        {0.1: 1.23, 1.0: 1.45, 10.0: 1.67, 18.0: 1.78, 30.0: 1.89}

    Example (sweep):
        >>> dcir_results = simulate_dcir(
        ...     cell_design, kpis,
        ...     initial_soc=[0.2, 0.5, 0.8],
        ...     temperature_K=[273.15, 298.15, 318.15],
        ...     c_rate=[0.1, 1.0, 2.0]
        ... )
        >>> print(dcir_results["num_simulations"])
        27
    """
    if cell_design is None:
        return {"success": False, "error": "cell_design is None"}

    if kpis is None:
        return {"success": False, "error": "kpis is None"}

    nominal_capacity = kpis.get("nominal_capacity").get("value")

    if nominal_capacity is None:
        return {
            "success": False,
            "error": "Nominal capacity not found in kpis",
        }

    # Convert inputs to arrays
    soc_array = np.atleast_1d(initial_soc)
    temp_array = np.atleast_1d(temperature_K)
    crate_array = np.atleast_1d(c_rate)

    # Check if this is a sweep (any input has more than one value)
    is_sweep = len(soc_array) > 1 or len(temp_array) > 1 or len(crate_array) > 1

    if is_sweep:
        return _run_pybamm_spmet_dcir(
            cell_design=cell_design,
            kpis=kpis,
            soc_array=soc_array,
            temp_array=temp_array,
            crate_array=crate_array,
            contact_resistance=contact_resistance,
        )

    # Single point simulation - continue with original logic
    initial_soc = float(soc_array[0])
    temperature_K = float(temp_array[0])
    c_rate = float(crate_array[0])

    # Calculate cell volume from dimensions if not directly available
    if "cell_volume" in cell_design:
        cell_vol_m3 = cell_design["cell_volume"]["value"] / 1000.0
    else:
        dims = cell_design.get("cell_dimensions")
        h_mm = dims.get("height").get("value")
        w_mm = dims.get("width").get("value")
        t_mm = dims.get("thickness").get("value")
        cell_vol_m3 = (h_mm * w_mm * t_mm) / 1e9

    # Get voltage cutoffs from cell design
    upper_voltage = cell_design.get("upper_voltage_cutoff").get("value")
    lower_voltage = cell_design.get("lower_voltage_cutoff").get("value")

    # Build simulation config
    simulation_config = {
        "ambient_temperature": temperature_K,
        "initial_temperature": temperature_K,
        "contact_resistance": contact_resistance,
        "upper_voltage_cutoff": upper_voltage,
        "lower_voltage_cutoff": lower_voltage,
        "total_heat_transfer_coefficient": 0.01,
        "cooling_surface_area": 0.1,
    }

    # Update cell_design with voltage cutoffs and volume if needed
    cell_design_copy = cell_design.copy()
    cell_design_copy["upper_voltage_cutoff"] = {"value": upper_voltage}
    cell_design_copy["lower_voltage_cutoff"] = {"value": lower_voltage}
    if "cell_volume" not in cell_design_copy:
        cell_design_copy["cell_volume"] = {"value": cell_vol_m3 * 1000.0}

    # Build parameters (includes calibration) using shared function
    default_params, model_options = _build_pybamm_params(
        cell_design_copy, simulation_config
    )

    # Run DCIR pulse simulation
    print("\n" + "=" * 80)
    print("DCIR PULSE SIMULATION")
    print("=" * 80)
    print(
        f"Conditions: SOC={initial_soc*100:.0f}%, T={temperature_K-273.15:.1f}°C, C-rate={c_rate}"
    )

    pulse_duration = 30.0
    exp_str = f"Discharge at {c_rate}C for {pulse_duration} seconds"

    experiment = pybamm.Experiment(
        [
            ("Rest for 1 seconds",),
            (exp_str,),
        ],
        period="0.01 second",
    )

    model = pybamm.lithium_ion.SPMe(options=model_options)
    model.variables["Anode potential [V]"] = model.variables[
        "Negative electrode surface potential difference at separator interface [V]"
    ]

    var_pts = {"x_n": 10, "x_s": 10, "x_p": 10, "r_n": 10, "r_p": 10}
    solver = pybamm.IDAKLUSolver(
        atol=1e-4,
        rtol=1e-4,
        output_variables=[
            "Time [s]",
            "Terminal voltage [V]",
            "Current [A]",
            "Discharge capacity [A.h]",
            "Discharge energy [W.h]",
            "Volume-averaged cell temperature [K]",
            "Power [W]",
            "Anode potential [V]",
            # Overpotential decomposition
            "Sum of x-averaged negative electrode reaction overpotentials [V]",
            "X-averaged negative electrode concentration overpotential [V]",
            "Negative electrode SEI film overpotential [V]",
            "Ohmic losses [V]",
        ],
    )

    sim = pybamm.Simulation(
        model,
        parameter_values=default_params,
        experiment=experiment,
        var_pts=var_pts,
    )

    try:
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        # Extract pulse cycle data
        if hasattr(solution, "cycles") and len(solution.cycles) > 1:
            data_source = solution.cycles[1]
        else:
            data_source = solution

        time_s = data_source["Time [s]"].entries
        voltage_V = data_source["Terminal voltage [V]"].entries

        # Extract overpotential data with try/except for graceful fallback
        try:
            reaction_overpotential = data_source[
                "Sum of x-averaged negative electrode reaction overpotentials [V]"
            ].entries
        except (KeyError, AttributeError):
            reaction_overpotential = np.zeros_like(time_s)

        try:
            concentration_overpotential = data_source[
                "X-averaged negative electrode concentration overpotential [V]"
            ].entries
        except (KeyError, AttributeError):
            concentration_overpotential = np.zeros_like(time_s)

        try:
            sei_overpotential = data_source[
                "Negative electrode SEI film overpotential [V]"
            ].entries
        except (KeyError, AttributeError):
            sei_overpotential = np.zeros_like(time_s)

        try:
            ohmic_overpotential = data_source["Ohmic losses [V]"].entries
        except (KeyError, AttributeError):
            ohmic_overpotential = np.zeros_like(time_s)

        # Ensure all arrays are 1D and properly shaped
        time_s = np.atleast_1d(time_s).ravel()
        voltage_V = np.atleast_1d(voltage_V).ravel()
        reaction_overpotential = np.atleast_1d(reaction_overpotential).ravel()
        concentration_overpotential = np.atleast_1d(concentration_overpotential).ravel()
        sei_overpotential = np.atleast_1d(sei_overpotential).ravel()
        ohmic_overpotential = np.atleast_1d(ohmic_overpotential).ravel()

        # Calculate DCIR at requested time points
        v_rest = voltage_V[0]
        i_amplitude = nominal_capacity * c_rate

        requested_points = [0.1, 1.0, 10.0, 18.0, 30.0]
        dcir_mOhm = {}
        overpotentials = {}

        print("\nDCIR Results:")
        print("-" * 40)

        for t_point in requested_points:
            # Find index closest to the requested time point relative to start
            t_idx_raw = np.argmin(np.abs(time_s - time_s[0] - t_point))

            # Ensure index is within bounds (handle case where requested time exceeds simulation time)
            max_idx = len(time_s) - 1
            t_idx = int(np.clip(t_idx_raw, 0, max_idx))

            v_pulse = voltage_V[t_idx]
            dcir_ohm = (v_rest - v_pulse) / i_amplitude + contact_resistance
            dcir_mOhm[t_point] = float(dcir_ohm * 1000)

            # Store overpotentials at this time point
            overpotentials[t_point] = {
                "reaction_overpotential_V": float(reaction_overpotential[t_idx]),
                "concentration_overpotential_V": float(
                    concentration_overpotential[t_idx]
                ),
                "sei_overpotential_V": float(sei_overpotential[t_idx]),
                "ohmic_overpotential_V": float(ohmic_overpotential[t_idx]),
            }
            print(f"  t={t_point:5.1f}s: DCIR = {dcir_mOhm[t_point]:.3f} mOhm")

        print("-" * 40)
        print("DCIR simulation completed successfully!")
        result = {
            "success": True,
            "dcir_mOhm": dcir_mOhm,
            "overpotentials": overpotentials,
            "conditions": {
                "initial_soc": initial_soc,
                "temperature_K": temperature_K,
                "temperature_C": temperature_K - 273.15,
                "c_rate": c_rate,
                "contact_resistance_Ohm": contact_resistance,
            },
        }

        return result

    except pybamm.SolverError as e:
        return {"success": False, "error": f"DCIR simulation failed: {str(e)}"}


def _run_pybamm_spmet_dcir(
    cell_design: dict,
    kpis: dict,
    soc_array: np.ndarray,
    temp_array: np.ndarray,
    crate_array: np.ndarray,
    contact_resistance: float = 1e-5,
) -> dict:
    """
    Run DCIR sweep across multiple SOC, temperature, and C-rate values.

    This internal function handles the sweep logic, running capacity calibration once
    and then iterating through all combinations of operating conditions.

    Args:
        cell_design: Cell design parameters dictionary
        kpis: KPIs dictionary containing nominal_capacity
        soc_array: Array of SOC values [0-1]
        temp_array: Array of temperatures [K]
        crate_array: Array of C-rates
        contact_resistance: Contact resistance [Ohm]

    Returns:
        Dictionary with surface_data containing DCIR at all operating points
    """
    nominal_capacity = kpis.get("nominal_capacity").get("value")

    # Build PyBaMM parameters from cell design (done once)

    if (
        cell_design["positive_electrode"]["coating"]["formulation"][
            "primary_active_material"
        ]["name"]
        == "LFP"
    ):
        default_params = pybamm.ParameterValues("Prada2013")
    else:
        default_params = pybamm.ParameterValues("ORegan2022")

    # Cell parameters
    cell_params = {
        "Nominal cell capacity [A.h]": nominal_capacity,
    }

    # Positive electrode parameters
    number_of_coated_sides = 2
    pos_electrode = cell_design["positive_electrode"]

    positive_electrode_params = {
        "Number of electrodes connected in parallel to make a cell": (
            pos_electrode["count"]["value"]
            * cell_design["jelly_roll"]["count"]["value"]
            * number_of_coated_sides
        ),
        "Electrode height [m]": pos_electrode["height"]["value"] / 1000,
        "Electrode width [m]": pos_electrode["width"]["value"] / 1000,
        "Electrode length [m]": pos_electrode["width"]["value"] / 1000,
        "Positive electrode thickness [m]": pos_electrode["coating"]["thickness"][
            "value"
        ]
        / 1e6,
        "Positive electrode porosity": pos_electrode["coating"]["porosity"]["value"],
        "Positive electrode active material volume fraction": pos_electrode["coating"][
            "active_material_volume_fraction"
        ]["value"],
        "Positive electrode density [kg.m-3]": pos_electrode["coating"]["density"][
            "value"
        ]
        * 1000,
    }

    positive_cc_params = {
        "Positive current collector thickness [m]": pos_electrode["foil"]["thickness"][
            "value"
        ]
        / 1e6,
    }

    # Negative electrode parameters
    neg_electrode = cell_design["negative_electrode"]

    negative_electrode_params = {
        "Negative electrode thickness [m]": neg_electrode["coating"]["thickness"][
            "value"
        ]
        / 1e6,
        "Negative electrode porosity": neg_electrode["coating"]["porosity"]["value"],
        "Negative electrode active material volume fraction": neg_electrode["coating"][
            "active_material_volume_fraction"
        ]["value"],
        "Negative electrode density [kg.m-3]": neg_electrode["coating"]["density"][
            "value"
        ]
        * 1000,
    }

    negative_cc_params = {
        "Negative current collector thickness [m]": neg_electrode["foil"]["thickness"][
            "value"
        ]
        / 1e6,
    }

    # Separator parameters
    separator = cell_design["separator"]
    separator_params = {
        "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
        "Separator porosity": separator["porosity"]["value"],
        "Separator density [kg.m-3]": (
            separator["material"]["density"]["value"] * 1000
        ),
    }

    # Get voltage cutoffs from cell design
    upper_voltage = cell_design.get("upper_voltage_cutoff").get("value")
    lower_voltage = cell_design.get("lower_voltage_cutoff").get("value")

    # Thermal parameters (will be updated per temperature)
    # Calculate cell volume from dimensions if not directly available
    if "cell_volume" in cell_design:
        cell_vol_m3 = cell_design["cell_volume"]["value"] / 1000.0
    else:
        # Calculate from dimensions: height × width × thickness (in mm³ → m³)
        dims = cell_design.get("cell_dimensions")
        h_mm = dims.get("height").get("value")
        w_mm = dims.get("width").get("value")
        t_mm = dims.get("thickness").get("value")
        cell_vol_m3 = (h_mm * w_mm * t_mm) / 1e9  # mm³ to m³

    thermal_params = {
        "Reference temperature [K]": 298.15,
        "Total heat transfer coefficient [W.m-2.K-1]": 0.01,
        "Cell cooling surface area [m2]": 0.1,
        "Cell volume [m3]": cell_vol_m3,
    }

    # Combine base parameters
    base_params = {
        **cell_params,
        **positive_electrode_params,
        **positive_cc_params,
        **negative_electrode_params,
        **negative_cc_params,
        **separator_params,
        **thermal_params,
    }

    default_params.update(base_params, check_already_exists=False)

    # Set PyBaMM model options
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    # Capacity calibration (done once at reference temperature)
    ref_temp = 298.15
    target_capacity_Ah = cell_design["nominal_capacity"]["value"]

    # Set reference temperature for calibration
    default_params.update(
        {
            "Ambient temperature [K]": ref_temp,
            "Initial temperature [K]": ref_temp,
            "Contact resistance [Ohm]": contact_resistance,
            "Upper voltage cut-off [V]": upper_voltage,
            "Lower voltage cut-off [V]": lower_voltage,
        },
        check_already_exists=False,
    )

    charge_step = f"Charge at 0.1C until {upper_voltage} V"
    hold_step = f"Hold at {upper_voltage} V for 2 hours or until C/50"
    discharge_step = f"Discharge at 0.1C for 15 hours or until {lower_voltage} V"

    capacity_match_experiment = pybamm.Experiment(
        [
            ("Rest for 1 seconds", charge_step, hold_step),
            ("Rest for 3600 seconds",),
            (discharge_step,),
            ("Rest for 1 seconds",),
        ],
        period="1 second",
    )

    model_capacity = pybamm.lithium_ion.SPMe(options=model_options)

    MAX_ITERATIONS = 20
    TOLERANCE = 0.0001

    for iteration in range(MAX_ITERATIONS):
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=default_params,
        )

        try:
            sol_capacity = sim_capacity.solve(
                solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
            )
        except pybamm.SolverError as e:
            return {"success": False, "error": f"Capacity calibration failed: {e}"}

        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            break

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah

        if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
            ocv_100 = float(sol_capacity.cycles[1]["Terminal voltage [V]"].entries[-1])
            ocv_0 = float(sol_capacity.cycles[3]["Terminal voltage [V]"].entries[-1])

            default_params.update(
                {
                    "Open-circuit voltage at 100% SOC [V]": ocv_100,
                    "Open-circuit voltage at 0% SOC [V]": ocv_0,
                },
                check_already_exists=False,
            )
            break

        new_width = default_params["Electrode width [m]"] / scale_factor
        default_params.update(
            {
                "Electrode width [m]": new_width,
                "Nominal cell capacity [A.h]": discharge_capacity / scale_factor,
            },
            check_already_exists=False,
        )
    else:
        print(f"Warning: Did not converge after {MAX_ITERATIONS} iterations")

    # Now run DCIR sweep
    print("\n" + "=" * 80)
    print("RUNNING DCIR SWEEP")
    print("=" * 80)

    surface_data = []
    sim_count = 0
    requested_points = [0.1, 1.0, 10.0, 18.0, 30.0]
    pulse_duration = 30.0

    for temp_K in temp_array:
        temp_C = temp_K - 273.15
        print(f"\n--- Temperature: {temp_C:.0f}°C ---")

        # Update temperature in parameters
        default_params.update(
            {
                "Ambient temperature [K]": float(temp_K),
                "Initial temperature [K]": float(temp_K),
            },
            check_already_exists=False,
        )

        for soc in soc_array:
            for c_rate in crate_array:
                sim_count += 1

                # Build experiment for this C-rate
                exp_str = f"Discharge at {c_rate}C for {pulse_duration} seconds"
                experiment = pybamm.Experiment(
                    [("Rest for 1 seconds",), (exp_str,)],
                    period="0.1 second",
                )

                model = pybamm.lithium_ion.SPMe(options=model_options)
                model.variables["Anode potential [V]"] = model.variables[
                    "Negative electrode surface potential difference at separator interface [V]"
                ]

                var_pts = {"x_n": 10, "x_s": 10, "x_p": 10, "r_n": 10, "r_p": 10}
                solver = pybamm.IDAKLUSolver(
                    atol=1e-4,
                    rtol=1e-4,
                    output_variables=[
                        "Time [s]",
                        "Terminal voltage [V]",
                        "Current [A]",
                        "Discharge capacity [A.h]",
                    ],
                )

                sim = pybamm.Simulation(
                    model,
                    parameter_values=default_params,
                    experiment=experiment,
                    var_pts=var_pts,
                )

                try:
                    solution = sim.solve(initial_soc=float(soc), solver=solver)

                    # Extract pulse cycle data
                    if hasattr(solution, "cycles") and len(solution.cycles) > 1:
                        data_source = solution.cycles[1]
                    else:
                        data_source = solution

                    time_s = data_source["Time [s]"].entries
                    voltage_V = data_source["Terminal voltage [V]"].entries

                    # Calculate DCIR at requested time points
                    v_rest = voltage_V[0]
                    i_amplitude = nominal_capacity * c_rate

                    dcir_mOhm = {}
                    for t_point in requested_points:
                        t_idx_raw = np.argmin(np.abs(time_s - time_s[0] - t_point))

                        # Ensure index is within bounds
                        t_idx = int(np.clip(t_idx_raw, 0, len(time_s) - 1))

                        actual_time = time_s[t_idx] - time_s[0]

                        if actual_time >= t_point * 0.9:
                            v_pulse = voltage_V[t_idx]
                            dcir_ohm = (
                                v_rest - v_pulse
                            ) / i_amplitude + contact_resistance
                            dcir_mOhm[t_point] = float(dcir_ohm * 1000)
                        else:
                            dcir_mOhm[t_point] = np.nan

                    surface_data.append(
                        {
                            "soc": float(soc),
                            "soc_pct": float(soc * 100),
                            "temperature_K": float(temp_K),
                            "temperature_C": float(temp_C),
                            "c_rate": float(c_rate),
                            "dcir_mOhm": dcir_mOhm,
                            "success": True,
                        }
                    )

                    # Print 10s DCIR as summary
                    dcir_10s = dcir_mOhm.get(10.0)
                    if not np.isnan(dcir_10s):
                        print(
                            f"  SOC={soc*100:.0f}%, C={c_rate}C: DCIR@10s = {dcir_10s:.3f} mΩ"
                        )
                    else:
                        print(f"  SOC={soc*100:.0f}%, C={c_rate}C: Pulse ended early")

                except pybamm.SolverError as e:
                    print(f"  SOC={soc*100:.0f}%, C={c_rate}C: Failed - {str(e)[:40]}")
                    surface_data.append(
                        {
                            "soc": float(soc),
                            "soc_pct": float(soc * 100),
                            "temperature_K": float(temp_K),
                            "temperature_C": float(temp_C),
                            "c_rate": float(c_rate),
                            "dcir_mOhm": {t: np.nan for t in requested_points},
                            "success": False,
                            "error": str(e),
                        }
                    )

    print("\n" + "=" * 80)
    print(f"Completed {sim_count} simulations")
    print("=" * 80)

    return {
        "success": True,
        "surface_data": surface_data,
        "sweep_params": {
            "soc_values": soc_array.tolist(),
            "temperature_K_values": temp_array.tolist(),
            "temperature_C_values": (temp_array - 273.15).tolist(),
            "c_rate_values": crate_array.tolist(),
        },
        "num_simulations": sim_count,
        "dcir_time_points_s": requested_points,
    }
