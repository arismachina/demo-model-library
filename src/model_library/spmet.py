"""
SPMeT (Single Particle Model with electrolyte and Thermal) Module

Unified PyBaMM model that takes experiment strings via simulation config
and returns raw time series data for post-processing.
"""

import pybamm
import numpy as np
import re


def run_spmet(
    cell_design: dict,
    simulation_config: dict | None = None,
) -> list[dict]:
    """
    Run SPMeT simulation with specified experiment configuration.

    This function handles:
    1. Model parameter setup from cell design manifest
    2. Capacity calibration via electrode width adjustment
    3. Running the specified experiment(s)
    4. Returning raw time series data

    Args:
        cell_design: Cell design parameters dictionary

        simulation_config: Simulation configuration dictionary containing:
            - temperature_K: Temperature [K] (default: 298.15)
            - initial_soc: Initial state of charge [0-1] (default: 1.0)
            - experiments: List of PyBaMM experiment strings to run
            - experiment_labels: List of labels for each experiment (optional)
            - period: Sampling period string (default: "1 second")
            - lower_voltage_cutoff: Lower voltage cutoff [V] (default: 2.5)
            - upper_voltage_cutoff: Upper voltage cutoff [V] (default: 3.65)
            - contact_resistance: Contact resistance [Ohm] (default: 1e-5)
            - drive_cycle: Dict with drive cycle data (optional, alternative to experiments):
                - time_s: Array of time points [s]
                - power_W: Array of power values [W] (positive = discharge), OR
                - c_rate: Array of C-rate values (positive = discharge)
                - label: Label for the drive cycle (optional)

    Returns:
        List of dictionaries, one per experiment, each containing:
            - time_s: Array of time points [s]
            - voltage_V: Array of terminal voltages [V]
            - current_A: Array of currents [A]
            - temperature_K: Array of cell temperatures [K]
            - capacity_Ah: Array of discharge capacity [Ah]
            - energy_Wh: Array of discharge energy [Wh]
            - power_W: Array of power [W]
            - experiment_label: Label for this experiment
            - success: Boolean indicating if simulation succeeded
            - error: Error message if failed (optional)
            - config: Configuration used

    Example:
        >>> config = {
        ...     "initial_soc": 1.0,
        ...     ...
        ... }
        >>> results = run_spmet(cell_design, config)
    """
    if simulation_config is None:
        raise ValueError("simulation_config must be provided")

    # Convert old-style config (c_rate, duration_s, direction) to new experiments format
    if "experiments" not in simulation_config and "c_rate" in simulation_config:
        c_rate = simulation_config.get("c_rate", 1.0)
        duration_s = simulation_config.get("duration_s", 30)
        direction = simulation_config.get("direction", "discharge")

        # Don't include voltage cutoff - let the simulation run for the specified duration
        # Voltage cutoffs with high C-rates can cause "infeasible" errors due to IR drop
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

    # Build PyBaMM parameters from manifest
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

    # Capacity calibration
    target_capacity_Ah = cell_design["nominal_capacity"]["value"]
    # Calibrate electrode width to match target capacity.
    print("\n" + "=" * 80)
    print("CAPACITY CALIBRATION")
    print("=" * 80)
    print(f"Target capacity: {target_capacity_Ah:.2f} Ah")
    I_0_33C = target_capacity_Ah / 3
    I_0_1C = target_capacity_Ah / 10

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

    print(f"Convergence tolerance: {TOLERANCE*100:.3f}%")
    print("-" * 80)

    for iteration in range(MAX_ITERATIONS):
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=default_params,
        )

        try:
            # Don't use initial_soc - let PyBaMM use the initial concentrations we set
            sol_capacity = sim_capacity.solve(
                solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
            )
        except pybamm.SolverError as e:
            print(f"Capacity calibration failed: {e}")
            raise

        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            print(f"Warning: Insufficient cycles: {len(sol_capacity.cycles)}")
            # Print cycles termination conditions
            for i in range(len(sol_capacity.cycles)):
                print(f"Cycle {i+1}: {sol_capacity.cycles[i]['Current [A]'].entries}")
                print(
                    f"Cycle {i+1}: {sol_capacity.cycles[i]['Terminal voltage [V]'].entries}"
                )
                print(f"Cycle {i+1}: {sol_capacity.cycles[i].termination}")
            break

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah
        error_percent = abs(1 - scale_factor) * 100

        print(
            f"Iteration {iteration+1:2d}: Capacity = {discharge_capacity:6.2f} Ah, Error = {error_percent:6.3f}%"
        )

        if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
            print("-" * 80)
            print(f"Converged after {iteration+1} iterations!")

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

    # Check for drive cycle mode
    drive_cycle = simulation_config.get("drive_cycle")

    if drive_cycle is not None:
        # Drive cycle mode: use time-power data directly
        return _run_drive_cycle(
            drive_cycle=drive_cycle,
            simulation_config=simulation_config,
            default_params=default_params,
            model_options=model_options,
        )

    # Get experiments from config
    experiments = simulation_config.get("experiments")
    experiment_labels = simulation_config.get("experiment_labels")

    if not experiments:
        raise ValueError(
            "No experiments provided in simulation_config['experiments'] or 'drive_cycle'"
        )

    # Pad labels if needed
    while len(experiment_labels) < len(experiments):
        experiment_labels.append(f"exp_{len(experiment_labels)}")

    print("\n" + "=" * 80)
    print("RUNNING EXPERIMENTS")
    print("=" * 80)

    initial_soc = simulation_config.get("initial_soc")
    period = simulation_config.get("period")

    # Define solver and points outside loop
    var_pts = {"x_n": 20, "x_s": 20, "x_p": 20, "r_n": 20, "r_p": 20}
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
        ],
    )

    all_results = []
    for exp_str, label in zip(experiments, experiment_labels):
        print(f"\nRunning: {label}")
        print(f"  Experiment: {exp_str[:60]}{'...' if len(exp_str) > 60 else ''}")

        # Get thresholds from config
        anode_threshold = simulation_config.get("anode_potential_threshold_V", 0.02)
        temp_threshold = simulation_config.get("jelly_roll_temperature_threshold_K")
        upper_voltage = simulation_config["upper_voltage_cutoff"]
        lower_voltage = simulation_config["lower_voltage_cutoff"]
        max_time_s = simulation_config.get("max_charge_time_s", 3600)

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

        # Check if this is a fast charge with anode potential riding
        if simulation_config.get("ride_anode_potential"):
            # Fast charge mode: CC -> Anode riding -> CV
            cv_termination = simulation_config.get("cv_termination_c_rate", 0.05)

            # Build terminations for anode riding phase
            riding_terminations = [f"{upper_voltage}V"]
            if temp_threshold is not None:
                riding_terminations.append(
                    pybamm.step.CustomTermination(
                        "Jelly roll temperature cut-off [K]", temperature_cutoff
                    )
                )

            # Create custom step to ride anode potential plateau
            anode_potential_step = pybamm.step.CustomStepImplicit(
                anode_potential_cutoff,
                direction="charge",
                duration=max_time_s,
                termination=riding_terminations,
            )

            # CC phase terminations
            cc_terminations = [
                pybamm.step.CustomTermination(
                    "Anode potential cut-off [V]", anode_potential_cutoff
                ),
                f"{upper_voltage}V",
            ]
            if temp_threshold is not None:
                cc_terminations.append(
                    pybamm.step.CustomTermination(
                        "Jelly roll temperature cut-off [K]", temperature_cutoff
                    )
                )

            # Parse C-rate from experiment string (e.g., "Charge at 10C for 3600 seconds")
            c_rate_match = re.search(r"at\s+([\d.]+)C", exp_str)
            c_rate = float(c_rate_match.group(1)) if c_rate_match else 1.0

            # CV hold with time limit
            cv_hold_step = pybamm.step.voltage(
                upper_voltage,
                duration=max_time_s,
                termination=f"C/{int(1/cv_termination)}",
            )

            experiment = pybamm.Experiment(
                [
                    (
                        # Phase 1: CC charge until anode potential threshold
                        pybamm.step.c_rate(
                            -c_rate,
                            duration=max_time_s,
                            termination=cc_terminations,
                        ),
                        # Phase 2: Ride anode potential plateau
                        anode_potential_step,
                        # Phase 3: CV hold until low current or time limit
                        cv_hold_step,
                    ),
                ],
                period=period,
                termination=f"{max_time_s} seconds",
            )

        elif termination_conditions:
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

            # For fast charge with anode riding, use full solution; otherwise extract cycle
            if simulation_config.get("ride_anode_potential"):
                data_source = solution
            elif hasattr(solution, "cycles") and len(solution.cycles) > 1:
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

            print(f"  Completed: {len(result['time_s'])} data points")
            all_results.append(result)

        except pybamm.SolverError as e:
            print(f"  Failed: {str(e)[:60]}")

    return all_results


def _run_drive_cycle(
    drive_cycle: dict,
    simulation_config: dict,
    default_params: pybamm.ParameterValues,
    model_options: dict,
) -> list[dict]:
    """
    Run a drive cycle simulation with time-varying power or C-rate input.

    Args:
        drive_cycle: Dict containing:
            - time_s: Array of time points [s]
            - power_W: Array of power values [W] (positive = discharge), OR
            - c_rate: Array of C-rate values (positive = discharge)
            - label: Optional label for the drive cycle
        simulation_config: Full simulation configuration
        default_params: Calibrated PyBaMM parameters
        model_options: PyBaMM model options

    Returns:
        List with single result dictionary
    """
    print("\n" + "=" * 80)
    print("RUNNING DRIVE CYCLE")
    print("=" * 80)

    time_s = np.array(drive_cycle["time_s"])
    label = drive_cycle.get("label", "drive_cycle")

    # Determine drive cycle type: power_W or c_rate
    if "power_W" in drive_cycle:
        drive_type = "power"
        values = np.array(drive_cycle["power_W"])
        print(f"  Type: Power")
        print(f"  Power range: {values.min():.1f} to {values.max():.1f} W")
        drive_data = np.column_stack((time_s, values))
        drive_cycle_step = pybamm.step.power(drive_data, duration=time_s[-1])
    elif "c_rate" in drive_cycle:
        drive_type = "c_rate"
        values = np.array(drive_cycle["c_rate"])
        print(f"  Type: C-rate")
        print(f"  C-rate range: {values.min():.3f} to {values.max():.3f} C")
        drive_data = np.column_stack((time_s, values))
        drive_cycle_step = pybamm.step.c_rate(drive_data, duration=time_s[-1])
    else:
        raise ValueError("drive_cycle must contain either 'power_W' or 'c_rate'")

    print(f"  Label: {label}")
    print(f"  Duration: {time_s[-1]:.1f} s ({time_s[-1]/60:.1f} min)")
    print(f"  Data points: {len(time_s)}")

    period = simulation_config.get("period", "1 second")
    experiment = pybamm.Experiment(
        [drive_cycle_step],
        period=period,
    )

    # Create model
    model = pybamm.lithium_ion.SPMe(options=model_options)

    # Add anode potential variable
    model.variables["Anode potential [V]"] = model.variables[
        "Negative electrode surface potential difference at separator interface [V]"
    ]

    # Setup simulation
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
        ],
    )

    sim = pybamm.Simulation(
        model,
        parameter_values=default_params,
        experiment=experiment,
        var_pts=var_pts,
    )

    initial_soc = simulation_config.get("initial_soc", 0.8)

    try:
        print(f"  Running simulation (initial SOC: {initial_soc*100:.0f}%)...")
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        result = {
            "time_s": solution["Time [s]"].entries,
            "voltage_V": solution["Terminal voltage [V]"].entries,
            "current_A": solution["Current [A]"].entries,
            "temperature_K": solution["Volume-averaged cell temperature [K]"].entries,
            "capacity_Ah": solution["Discharge capacity [A.h]"].entries,
            "energy_Wh": solution["Discharge energy [W.h]"].entries,
            "power_W": solution["Power [W]"].entries,
            "anode_potential_V": solution["Anode potential [V]"].entries,
            "experiment_label": label,
            "success": True,
            "config": simulation_config,
        }

        print(f"  Completed: {len(result['time_s'])} data points")
        return [result]

    except pybamm.SolverError as e:
        print(f"  Failed: {str(e)[:100]}")
        return [
            {
                "experiment_label": label,
                "success": False,
                "error": str(e),
                "config": simulation_config,
            }
        ]
