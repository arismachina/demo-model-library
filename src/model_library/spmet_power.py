"""
SPMeT Power Module

Maximum discharge/charge power extraction via binary search.
Sweeps SOC, temperature, and pulse duration to find power envelope.
"""

import pybamm
import numpy as np


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

    MAX_ITERATIONS = 5  # REDUCED: Only 5 iterations instead of 20
    TOLERANCE = 0.001  # RELAXED: 0.1% tolerance instead of 0.01%

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
            break

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


def _power_sweep_characterization(
    soc: float,
    temp_K: float,
    pulse_duration_s: float,
    direction: str,
    config: dict,
    params: pybamm.ParameterValues,
    options: dict,
) -> dict:
    """
    Direct constant power sweep to find max power while respecting voltage limits.

    Algorithm:
    1. Start at 100 kW, reduce by order of magnitude (÷10) until feasible
    2. Once feasible found, increase by 10x to find upper bound
    3. Binary search between upper and lower bounds to find exact max power
    """
    upper_voltage = config["upper_voltage_cutoff"]
    lower_voltage = config["lower_voltage_cutoff"]

    # Setup simulation components
    var_pts = {"x_n": 20, "x_s": 20, "x_p": 20, "r_n": 20, "r_p": 20}

    output_vars = [
        "Time [s]",
        "Terminal voltage [V]",
        "Current [A]",
        "Power [W]",
    ]

    # Add overpotential variables
    overpotential_vars = [
        "Sum of x-averaged negative electrode reaction overpotentials [V]",
        "X-averaged negative electrode concentration overpotential [V]",
        "Negative electrode SEI film overpotential [V]",
        "Ohmic losses [V]",
    ]

    solver = pybamm.IDAKLUSolver(
        atol=1e-4,
        rtol=1e-4,
        output_variables=output_vars + overpotential_vars,
    )

    # Create model
    model = pybamm.lithium_ion.SPMe(options=options)

    def _test_power(power_W):
        """Test a single power level, return (feasible, result)"""
        if direction == "discharge":
            exp_str = f"Discharge at {power_W}W for {pulse_duration_s}s or until {lower_voltage}V"
        else:
            exp_str = f"Charge at {power_W}W for {pulse_duration_s}s or until {upper_voltage}V"

        experiment = pybamm.Experiment(
            [("Rest for 1 seconds"), (exp_str,)],
            period=config["period"],
        )

        sim = pybamm.Simulation(
            model,
            parameter_values=params,
            experiment=experiment,
            var_pts=var_pts,
        )

        try:
            # Suppress solver output for these intermediate tests
            import logging

            pybamm_logger = logging.getLogger("pybamm")
            old_level = pybamm_logger.level
            pybamm_logger.setLevel(logging.CRITICAL)

            solution = sim.solve(initial_soc=soc, solver=solver)

            pybamm_logger.setLevel(old_level)

            # Check if we have both rest and power cycles
            if not hasattr(solution, "cycles") or len(solution.cycles) < 2:
                return False, None

            # Extract power cycle (index 1, after rest at index 0)
            data_source = solution.cycles[1]
            actual_power = float(data_source["Power [W]"].entries[-1])

            # If power near zero, step was skipped (infeasible)
            if abs(actual_power) < 1.0:
                return False, None

            final_voltage = float(data_source["Terminal voltage [V]"].entries[-1])
            final_current = float(data_source["Current [A]"].entries[-1])

            # Check voltage bounds
            voltage_valid = lower_voltage <= final_voltage <= upper_voltage

            if not voltage_valid:
                return False, None

            # Valid result
            overpotentials = _extract_overpotentials(data_source)
            result = {
                "power_W": abs(actual_power),
                "current_A": abs(final_current),
                "voltage_V": final_voltage,
                "overpotentials": overpotentials,
            }
            return True, result

        except (pybamm.SolverError, Exception):
            return False, None

    # PHASE 1: Find feasible region by reducing from 10 kW by orders of magnitude
    power = 10000.0  # Start at 10 kW (more reasonable than 100kW)
    lower_bound_power = None
    lower_bound_result = None

    for reduction in range(10):  # Try down to 1 mW
        feasible, result = _test_power(power)
        if feasible:
            lower_bound_power = power
            lower_bound_result = result
            break
        power /= 10.0

    if lower_bound_power is None:
        # No feasible power found even at 1mW
        return {
            "power_W": 0.0,
            "current_A": 0.0,
            "voltage_V": 0.0,
            "converged": False,
            "overpotentials": {
                "reaction": None,
                "concentration": None,
                "sei": None,
                "ohmic": None,
            },
        }

    # PHASE 2: From feasible region, increase by 10x to find upper bound
    power = lower_bound_power * 10.0
    upper_bound_power = lower_bound_power
    upper_bound_result = lower_bound_result

    for attempt in range(10):  # Try up to 1000x higher
        feasible, result = _test_power(power)
        if feasible:
            upper_bound_power = power
            upper_bound_result = result
            power *= 10.0
        else:
            # Found first infeasible, stop
            break

    # PHASE 3: Binary search between bounds
    power_low = lower_bound_power
    power_high = upper_bound_power
    best_result = upper_bound_result

    max_iterations = 20
    for iteration in range(max_iterations):
        if (power_high - power_low) < 10.0:  # Within 10W tolerance
            break

        power_mid = (power_low + power_high) / 2

        feasible, result = _test_power(power_mid)

        if feasible:
            # Valid: search higher
            best_result = result
            power_low = power_mid
        else:
            # Infeasible: search lower
            power_high = power_mid

    return {
        "power_W": best_result["power_W"],
        "current_A": best_result["current_A"],
        "voltage_V": best_result["voltage_V"],
        "converged": True,
        "overpotentials": best_result["overpotentials"],
    }


def _extract_overpotentials(data_source) -> dict:
    """
    Extract overpotential values from PyBaMM solution.

    Safely handles scalar and array returns from PyBaMM variables.

    Args:
        data_source: PyBaMM cycle or solution data object

    Returns:
        Dictionary with overpotential values (or None if unavailable)
    """
    overpotentials = {
        "reaction": None,
        "concentration": None,
        "sei": None,
        "ohmic": None,
    }

    try:
        reaction_value = data_source[
            "Sum of x-averaged negative electrode reaction overpotentials [V]"
        ].entries[-1]
        overpotentials["reaction"] = float(
            reaction_value.flat[0]
            if (hasattr(reaction_value, "__len__") and len(reaction_value) > 0)
            else reaction_value
        )
    except (KeyError, AttributeError, TypeError, ValueError):
        pass

    try:
        concentration_value = data_source[
            "X-averaged negative electrode concentration overpotential [V]"
        ].entries[-1]
        overpotentials["concentration"] = float(
            concentration_value.flat[0]
            if (
                hasattr(concentration_value, "__len__") and len(concentration_value) > 0
            )
            else concentration_value
        )
    except (KeyError, AttributeError, TypeError, ValueError):
        pass

    try:
        sei_value = data_source[
            "Negative electrode SEI film overpotential [V]"
        ].entries[-1]
        overpotentials["sei"] = float(
            sei_value.flat[0]
            if (hasattr(sei_value, "__len__") and len(sei_value) > 0)
            else sei_value
        )
    except (KeyError, AttributeError, TypeError, ValueError):
        pass

    try:
        ohmic_value = data_source["Ohmic losses [V]"].entries[-1]
        overpotentials["ohmic"] = float(
            ohmic_value.flat[0]
            if (hasattr(ohmic_value, "__len__") and len(ohmic_value) > 0)
            else ohmic_value
        )
    except (KeyError, AttributeError, TypeError, ValueError):
        pass

    return overpotentials


def run_spmet_power(
    cell_design: dict,
    simulation_config: dict,
) -> list[dict]:
    """
    Run SPMeT power sweep to find max discharge/charge power.

    Uses direct power sweep (logarithmic spacing) to find maximum power
    while respecting voltage limits for each (SOC, temperature, duration) point.

    Key difference from old approach:
    - OLD: Binary search for C-rate that hits exact voltage target
    - NEW: Sweep power levels and measure voltage response, report max power
             that stays within [lower_voltage, upper_voltage] bounds

    This is more physically accurate because:
    1. Real hardware operates at constant power, not constant C-rate
    2. Voltage naturally varies within the permitted window
    3. Eliminates "infeasible" solver errors from searching invalid C-rate regions

    Args:
        cell_design: Cell design parameters dictionary

        simulation_config: Simulation configuration dictionary containing:
            - soc_array: Array of SOC points to test [0-1] (required)
            - temp_array: Array of temperatures to test [K] (required)
            - pulse_durations_s: Array of pulse durations to test [s] (required)
            - c_rate_min: Minimum C-rate proxy for power sweep (default: 0.1)
            - c_rate_max: Maximum C-rate proxy for power sweep (default: 10.0)
            - period: Sampling period string (default: "0.1 second")
            - upper_voltage_cutoff: Upper voltage cutoff [V] (required)
            - lower_voltage_cutoff: Lower voltage cutoff [V] (required)
            - contact_resistance: Contact resistance [Ohm] (required)
            - total_heat_transfer_coefficient: Heat transfer coefficient [W.m-2.K-1] (required)
            - cooling_surface_area: Cell cooling surface area [m2] (required)
            - ambient_temperature: Ambient temperature [K] (required)
            - initial_temperature: Initial temperature [K] (required)

    Returns:
        List of dictionaries, one per (SOC, temp, duration) point:
            - soc: State of charge tested
            - temperature_K: Temperature tested
            - pulse_duration_s: Pulse duration tested
            - max_discharge_power_W: Max discharge power (stays within voltage bounds)
            - max_discharge_crate: Equivalent C-rate at max discharge power
            - max_discharge_current_A: Current at max discharge power
            - max_discharge_voltage_V: Voltage at max discharge power
            - discharge_converged: Whether a valid power level was found
            - max_charge_power_W: Max charge power (stays within voltage bounds)
            - max_charge_crate: Equivalent C-rate at max charge power
            - max_charge_current_A: Current at max charge power
            - max_charge_voltage_V: Voltage at max charge power
            - charge_converged: Whether a valid power level was found
            - discharge_overpotentials: Dict with reaction/concentration/sei/ohmic [V]
            - charge_overpotentials: Dict with reaction/concentration/sei/ohmic [V]

    Example:
        >>> config = {
        ...     "soc_array": [0.2, 0.5, 0.8],
        ...     "temp_array": [278, 298, 323],
        ...     "pulse_durations_s": [1, 10, 30],
        ...     "upper_voltage_cutoff": 3.65,
        ...     "lower_voltage_cutoff": 2.5,
        ...     "contact_resistance": 1e-5,
        ...     "total_heat_transfer_coefficient": 10.0,
        ...     "cooling_surface_area": 0.1,
        ...     "ambient_temperature": 298.15,
        ...     "initial_temperature": 298.15,
        ... }
        >>> results = run_spmet_power(cell_design, config)
    """
    # Build parameters and calibrate
    default_params, model_options = _build_pybamm_params(cell_design, simulation_config)

    # Get sweep arrays
    soc_array = simulation_config["soc_array"]
    temp_array = simulation_config["temp_array"]
    pulse_durations = simulation_config["pulse_durations_s"]

    all_results = []
    point_num = 0
    total_points = len(soc_array) * len(temp_array) * len(pulse_durations)

    for soc in soc_array:
        for temp_K in temp_array:
            for pulse_duration_s in pulse_durations:
                point_num += 1

                # Update temperature in config
                config_copy = simulation_config.copy()
                config_copy["ambient_temperature"] = temp_K
                config_copy["initial_temperature"] = temp_K

                # Run power sweep characterization for discharge
                discharge_result = _power_sweep_characterization(
                    soc,
                    temp_K,
                    pulse_duration_s,
                    "discharge",
                    config_copy,
                    default_params,
                    model_options,
                )

                # Run power sweep characterization for charge
                charge_result = _power_sweep_characterization(
                    soc,
                    temp_K,
                    pulse_duration_s,
                    "charge",
                    config_copy,
                    default_params,
                    model_options,
                )

                result = {
                    "soc": soc,
                    "temperature_K": temp_K,
                    "pulse_duration_s": pulse_duration_s,
                    "max_discharge_power_W": discharge_result["power_W"],
                    "max_discharge_current_A": discharge_result["current_A"],
                    "max_discharge_voltage_V": discharge_result["voltage_V"],
                    "discharge_converged": discharge_result["converged"],
                    "max_charge_power_W": charge_result["power_W"],
                    "max_charge_current_A": charge_result["current_A"],
                    "max_charge_voltage_V": charge_result["voltage_V"],
                    "charge_converged": charge_result["converged"],
                    "discharge_overpotentials": discharge_result["overpotentials"],
                    "charge_overpotentials": charge_result["overpotentials"],
                }

                all_results.append(result)

    return all_results
