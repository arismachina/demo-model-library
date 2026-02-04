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


def _binary_search_max_crate(
    soc: float,
    temp_K: float,
    pulse_duration_s: float,
    direction: str,
    config: dict,
    params: pybamm.ParameterValues,
    options: dict,
) -> dict:
    """
    Binary search to find max C-rate that reaches voltage cutoff.

    Args:
        soc: State of charge [0-1]
        temp_K: Temperature [K]
        pulse_duration_s: Pulse duration [s]
        direction: 'discharge' or 'charge'
        config: Simulation configuration
        params: PyBaMM parameter values
        options: PyBaMM model options

    Returns:
        Dictionary with max power results
    """
    c_rate_min = config.get("c_rate_min", 0.1)
    c_rate_max = config.get("c_rate_max", 10.0)
    max_iterations = 10

    upper_voltage = config["upper_voltage_cutoff"]
    lower_voltage = config["lower_voltage_cutoff"]
    target_voltage = lower_voltage if direction == "discharge" else upper_voltage

    # Setup simulation components
    var_pts = {"x_n": 20, "x_s": 20, "x_p": 20, "r_n": 20, "r_p": 20}

    output_vars = [
        "Time [s]",
        "Terminal voltage [V]",
        "Current [A]",
        "Power [W]",
        "Anode potential [V]",
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

    # Create model once
    model = pybamm.lithium_ion.SPMe(options=options)
    model.variables["Anode potential [V]"] = model.variables[
        "Negative electrode surface potential difference at separator interface [V]"
    ]

    # Binary search
    c_rate_low = c_rate_min
    c_rate_high = c_rate_max
    best_result = None
    converged = False

    for iteration in range(max_iterations):
        c_rate_mid = (c_rate_low + c_rate_high) / 2

        # Create experiment
        if direction == "discharge":
            exp_str = f"Discharge at {c_rate_mid}C for {pulse_duration_s} seconds or until {target_voltage}V"
        else:
            exp_str = f"Charge at {c_rate_mid}C for {pulse_duration_s} seconds or until {target_voltage}V"

        experiment = pybamm.Experiment(
            [("Rest for 1 seconds"), (exp_str,)],
            period=config.get("period", "0.1 second"),
        )

        sim = pybamm.Simulation(
            model,
            parameter_values=params,
            experiment=experiment,
            var_pts=var_pts,
        )

        try:
            solution = sim.solve(initial_soc=soc, solver=solver)

            # Extract cycle data
            if hasattr(solution, "cycles") and len(solution.cycles) > 1:
                data_source = solution.cycles[1]
            else:
                data_source = solution

            final_voltage = float(data_source["Terminal voltage [V]"].entries[-1])
            final_current = float(data_source["Current [A]"].entries[-1])
            final_power = float(data_source["Power [W]"].entries[-1])

            # Check if we hit the voltage cutoff
            voltage_diff = abs(final_voltage - target_voltage)

            # Extract overpotentials at final point
            overpotentials = {}
            try:
                overpotentials["reaction"] = float(
                    data_source[
                        "Sum of x-averaged negative electrode reaction overpotentials [V]"
                    ].entries[-1]
                )
            except (KeyError, AttributeError):
                overpotentials["reaction"] = None

            try:
                overpotentials["concentration"] = float(
                    data_source[
                        "X-averaged negative electrode concentration overpotential [V]"
                    ].entries[-1]
                )
            except (KeyError, AttributeError):
                overpotentials["concentration"] = None

            try:
                overpotentials["sei"] = float(
                    data_source[
                        "Negative electrode SEI film overpotential [V]"
                    ].entries[-1]
                )
            except (KeyError, AttributeError):
                overpotentials["sei"] = None

            try:
                overpotentials["ohmic"] = float(
                    data_source["Ohmic losses [V]"].entries[-1]
                )
            except (KeyError, AttributeError):
                overpotentials["ohmic"] = None

            # Store result
            best_result = {
                "c_rate": c_rate_mid,
                "final_voltage": final_voltage,
                "current_A": final_current,
                "power_W": abs(final_power),
                "overpotentials": overpotentials,
            }

            # Check convergence (within 1 mV of target)
            if voltage_diff < 0.001:
                converged = True
                break

            # Adjust search range
            if direction == "discharge":
                if final_voltage > target_voltage:
                    # Need more discharge, increase C-rate
                    c_rate_low = c_rate_mid
                else:
                    # Discharged too much, decrease C-rate
                    c_rate_high = c_rate_mid
            else:  # charge
                if final_voltage < target_voltage:
                    # Need more charge, increase C-rate
                    c_rate_low = c_rate_mid
                else:
                    # Charged too much, decrease C-rate
                    c_rate_high = c_rate_mid

        except pybamm.SolverError:
            # If solver fails at this C-rate, reduce upper bound
            c_rate_high = c_rate_mid
            continue

    if best_result is None:
        return {
            "c_rate": 0.0,
            "power_W": 0.0,
            "current_A": 0.0,
            "converged": False,
            "overpotentials": {
                "reaction": None,
                "concentration": None,
                "sei": None,
                "ohmic": None,
            },
        }

    return {
        "c_rate": best_result["c_rate"],
        "power_W": best_result["power_W"],
        "current_A": best_result["current_A"],
        "converged": converged,
        "overpotentials": best_result["overpotentials"],
    }


def run_spmet_power(
    cell_design: dict,
    simulation_config: dict,
) -> list[dict]:
    """
    Run SPMeT power sweep to find max discharge/charge power.

    Uses binary search (10 iterations max) to find C-rate that reaches
    voltage cutoff exactly for each (SOC, temperature, duration) point.

    Args:
        cell_design: Cell design parameters dictionary

        simulation_config: Simulation configuration dictionary containing:
            - soc_array: Array of SOC points to test [0-1] (required)
            - temp_array: Array of temperatures to test [K] (required)
            - pulse_durations_s: Array of pulse durations to test [s] (required)
            - c_rate_min: Minimum C-rate for search (default: 0.1)
            - c_rate_max: Maximum C-rate for search (default: 10.0)
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
            - max_discharge_power_W: Max discharge power
            - max_discharge_crate: C-rate at max discharge power
            - max_discharge_current_A: Current at max discharge power
            - discharge_converged: Whether binary search converged
            - max_charge_power_W: Max charge power
            - max_charge_crate: C-rate at max charge power
            - max_charge_current_A: Current at max charge power
            - charge_converged: Whether binary search converged
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

    print("\n" + "=" * 80)
    print("RUNNING POWER SWEEP")
    print("=" * 80)
    print(f"SOC points: {len(soc_array)}")
    print(f"Temperature points: {len(temp_array)}")
    print(f"Pulse durations: {len(pulse_durations)}")
    print(
        f"Total combinations: {len(soc_array) * len(temp_array) * len(pulse_durations)}"
    )

    all_results = []
    point_num = 0
    total_points = len(soc_array) * len(temp_array) * len(pulse_durations)

    for soc in soc_array:
        for temp_K in temp_array:
            for pulse_duration_s in pulse_durations:
                point_num += 1
                print(
                    f"\n[{point_num}/{total_points}] SOC={soc:.2f}, T={temp_K:.1f}K, Duration={pulse_duration_s}s"
                )

                # Update temperature in config
                config_copy = simulation_config.copy()
                config_copy["ambient_temperature"] = temp_K
                config_copy["initial_temperature"] = temp_K

                # Search max discharge power
                print("  Searching max discharge power...")
                discharge_result = _binary_search_max_crate(
                    soc,
                    temp_K,
                    pulse_duration_s,
                    "discharge",
                    config_copy,
                    default_params,
                    model_options,
                )

                # Search max charge power
                print("  Searching max charge power...")
                charge_result = _binary_search_max_crate(
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
                    "max_discharge_crate": discharge_result["c_rate"],
                    "max_discharge_current_A": discharge_result["current_A"],
                    "discharge_converged": discharge_result["converged"],
                    "max_charge_power_W": charge_result["power_W"],
                    "max_charge_crate": charge_result["c_rate"],
                    "max_charge_current_A": charge_result["current_A"],
                    "charge_converged": charge_result["converged"],
                    "discharge_overpotentials": discharge_result["overpotentials"],
                    "charge_overpotentials": charge_result["overpotentials"],
                }

                print(
                    f"  Max discharge: {discharge_result['power_W']:.1f}W at {discharge_result['c_rate']:.2f}C"
                )
                print(
                    f"  Max charge: {charge_result['power_W']:.1f}W at {charge_result['c_rate']:.2f}C"
                )

                all_results.append(result)

    print("\n" + "=" * 80)
    print(f"COMPLETED: {len(all_results)} sweep points")
    print("=" * 80)

    return all_results
