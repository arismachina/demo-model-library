"""
SPMeT (Single Particle Model with electrolyte and Thermal) Module

Unified PyBaMM model that takes experiment strings via simulation config
and returns raw time series data for post-processing.
"""

import pybamm
import numpy as np
import re


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

    # Use C-rate syntax which PyBaMM handles better
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


def run_spmet(
    cell_design: dict,
    simulation_config: dict | None = None,
) -> list[dict]:
    """
    Run SPMeT simulation with specified experiment configuration.

    This function handles:
    1. Model parameter setup from cell design manifest
    2. Capacity calibration via electrode width adjustment
    3. Running the specified experiment(s) with custom terminations
    4. Returning raw time series data with overpotential breakdown

    Args:
        cell_design: Cell design parameters dictionary

        simulation_config: Simulation configuration dictionary containing:
            - experiments: List of PyBaMM experiment strings to run (required)
            - experiment_labels: List of labels for each experiment (optional)
            - initial_soc: Initial state of charge [0-1] (default: 0.8)
            - period: Sampling period string (default: "1 second")
            - lower_voltage_cutoff: Lower voltage cutoff [V] (required)
            - upper_voltage_cutoff: Upper voltage cutoff [V] (required)
            - contact_resistance: Contact resistance [Ohm] (required)
            - anode_potential_threshold_V: Anode potential cutoff [V] (optional)
            - jelly_roll_temperature_threshold_K: Temperature cutoff [K] (optional)
            - total_heat_transfer_coefficient: Heat transfer coefficient [W.m-2.K-1] (required)
            - cooling_surface_area: Cell cooling surface area [m2] (required)
            - ambient_temperature: Ambient temperature [K] (required)
            - initial_temperature: Initial temperature [K] (required)

    Returns:
        List of dictionaries, one per experiment, each containing:
            - time_s: Array of time points [s]
            - voltage_V: Array of terminal voltages [V]
            - current_A: Array of currents [A]
            - temperature_K: Array of cell temperatures [K]
            - capacity_Ah: Array of discharge capacity [Ah]
            - energy_Wh: Array of discharge energy [Wh]
            - power_W: Array of power [W]
            - anode_potential_V: Array of anode potentials [V]
            - reaction_overpotential_V: Array of reaction overpotentials [V] (if available)
            - concentration_overpotential_V: Array of concentration overpotentials [V] (if available)
            - sei_overpotential_V: Array of SEI overpotentials [V] (if available)
            - ohmic_overpotential_V: Array of ohmic losses [V] (if available)
            - experiment_label: Label for this experiment
            - success: Boolean indicating if simulation succeeded
            - error: Error message if failed (optional)
            - config: Configuration used

    Example:
        >>> config = {
        ...     "experiments": ["Discharge at 1C for 3600 seconds"],
        ...     "initial_soc": 1.0,
        ...     "upper_voltage_cutoff": 3.65,
        ...     "lower_voltage_cutoff": 2.5,
        ...     "contact_resistance": 1e-5,
        ...     "total_heat_transfer_coefficient": 10.0,
        ...     "cooling_surface_area": 0.1,
        ...     "ambient_temperature": 298.15,
        ...     "initial_temperature": 298.15,
        ... }
        >>> results = run_spmet(cell_design, config)
    """
    if simulation_config is None:
        raise ValueError("simulation_config must be provided")

    # Convert old-style config (c_rate, duration_s, direction) to new experiments format
    if "experiments" not in simulation_config and "c_rate" in simulation_config:
        c_rate = simulation_config.get("c_rate")
        duration_s = simulation_config.get("duration_s")
        direction = simulation_config.get("direction")

        if direction == "discharge":
            exp_str = f"Discharge at {c_rate}C for {duration_s} seconds"
        else:
            exp_str = f"Charge at {c_rate}C for {duration_s} seconds"

        simulation_config = {
            **simulation_config,
            "experiments": [exp_str],
            "experiment_labels": [f"{c_rate}C_{direction}"],
            "period": "0.1 second",
        }

    # Build PyBaMM parameters from manifest (includes calibration)
    default_params, model_options = _build_pybamm_params(cell_design, simulation_config)

    # Get experiments from config
    experiments = simulation_config.get("experiments")
    experiment_labels = simulation_config.get("experiment_labels")

    if not experiments:
        raise ValueError("No experiments provided in simulation_config['experiments']")

    # Initialize solver and points
    var_pts = {"x_n": 20, "x_s": 20, "x_p": 20, "r_n": 20, "r_p": 20}

    # Add overpotential variables to output
    output_vars = [
        "Time [s]",
        "Terminal voltage [V]",
        "Current [A]",
        "Discharge capacity [A.h]",
        "Discharge energy [W.h]",
        "Volume-averaged cell temperature [K]",
        "Power [W]",
        "Anode potential [V]",
    ]

    # Try to add overpotential variables (may not be available in all PyBaMM versions)
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

    initial_soc = simulation_config.get("initial_soc")
    period = simulation_config.get("period")
    all_results = []

    # ========== EXPERIMENT MODE ==========
    print("\n" + "=" * 80)
    print("RUNNING EXPERIMENTS")
    print("=" * 80)

    # Pad labels if needed
    while len(experiment_labels) < len(experiments):
        experiment_labels.append(f"exp_{len(experiment_labels)}")

    for exp_str, label in zip(experiments, experiment_labels):
        print(f"\nRunning: {label}")
        print(f"  Experiment: {exp_str[:60]}{'...' if len(exp_str) > 60 else ''}")

        # Get thresholds from config
        anode_threshold = simulation_config.get("anode_potential_threshold_V")
        temp_threshold = simulation_config.get("jelly_roll_temperature_threshold_K")
        upper_voltage = simulation_config["upper_voltage_cutoff"]
        lower_voltage = simulation_config["lower_voltage_cutoff"]
        max_time_s = simulation_config.get("max_charge_time_s")

        # Define cutoff functions
        def anode_potential_cutoff(variables):
            return variables["Anode potential [V]"] - anode_threshold

        def temperature_cutoff(variables):
            return temp_threshold - variables["Volume-averaged cell temperature [K]"]

        # Build termination conditions list
        termination_conditions = []

        if "anode_potential_threshold_V" in simulation_config:
            termination_conditions.append(
                pybamm.step.CustomTermination(
                    "Anode potential cut-off [V]", anode_potential_cutoff
                )
            )

        if temp_threshold is not None:
            termination_conditions.append(
                pybamm.step.CustomTermination(
                    "Jelly roll temperature cut-off [K]", temperature_cutoff
                )
            )

        if termination_conditions:
            # Standard mode with custom terminations
            base_exp_str = re.sub(r"\s+or until\s+[\d.]+\s*V", "", exp_str)

            # Determine voltage limit based on direction
            if "charge" in exp_str.lower():
                termination_conditions.append(f"{upper_voltage}V")
            else:
                termination_conditions.append(f"{lower_voltage}V")

            experiment = pybamm.Experiment(
                [
                    ("Rest for 1 seconds"),
                    (
                        pybamm.step.string(
                            base_exp_str,
                            termination=termination_conditions,
                        ),
                    ),
                ],
                period=period,
            )
        else:
            # Simple mode: use experiment string directly
            experiment = pybamm.Experiment(
                [
                    ("Rest for 1 seconds"),
                    (exp_str,),
                ],
                period=period,
            )

        # Common simulation logic for all experiment branches
        model = pybamm.lithium_ion.SPMe(options=model_options)

        # Add anode potential variable for lithium plating monitoring
        # Use potential at separator interface (minimum during charging, where plating occurs first)
        model.variables["Anode potential [V]"] = model.variables[
            "Negative electrode surface potential difference at separator interface [V]"
        ]

        sim = pybamm.Simulation(
            model,
            parameter_values=default_params,
            experiment=experiment,
            var_pts=var_pts,
        )

        try:
            solution = sim.solve(initial_soc=initial_soc, solver=solver)

            # Extract cycle data
            if hasattr(solution, "cycles") and len(solution.cycles) > 1:
                data_source = solution.cycles[1]
            else:
                data_source = solution

            result = {
                "time_s": data_source["Time [s]"].entries,
                "voltage_V": data_source["Terminal voltage [V]"].entries,
                "current_A": data_source["Current [A]"].entries,
                "temperature_K": data_source[
                    "Volume-averaged cell temperature [K]"
                ].entries,
                "capacity_Ah": data_source["Discharge capacity [A.h]"].entries,
                "energy_Wh": data_source["Discharge energy [W.h]"].entries,
                "power_W": data_source["Power [W]"].entries,
                "anode_potential_V": data_source["Anode potential [V]"].entries,
                "experiment_label": label,
                "success": True,
                "config": simulation_config,
            }

            # Try to extract overpotential data if available
            try:
                result["reaction_overpotential_V"] = data_source[
                    "Sum of x-averaged negative electrode reaction overpotentials [V]"
                ].entries
            except (KeyError, AttributeError):
                pass

            try:
                result["concentration_overpotential_V"] = data_source[
                    "X-averaged negative electrode concentration overpotential [V]"
                ].entries
            except (KeyError, AttributeError):
                pass

            try:
                result["sei_overpotential_V"] = data_source[
                    "Negative electrode SEI film overpotential [V]"
                ].entries
            except (KeyError, AttributeError):
                pass

            try:
                result["ohmic_overpotential_V"] = data_source[
                    "Ohmic losses [V]"
                ].entries
            except (KeyError, AttributeError):
                pass

            print(f"  Completed: {len(result['time_s'])} data points")
            all_results.append(result)

        except pybamm.SolverError as e:
            print(f"  Failed: {str(e)[:60]}")

    return all_results
