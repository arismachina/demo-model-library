"""
SPMeT Energy Module

Energy analysis with power profiles, auto-detecting charge/discharge phases
and calculating total round-trip efficiency.
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
    print(f"  Cell: {cell_design.get('name')}")
    print(f"  Nominal capacity: {cell_design.get('nominal_capacity').get('value')} Ah")

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

    print("\n[DEBUG] About to enter capacity calibration section")
    import sys

    sys.stdout.flush()

    # ========== CAPACITY CALIBRATION ==========
    target_capacity_Ah = cell_design["nominal_capacity"]["value"]

    print("\n" + "=" * 80)
    print("CAPACITY CALIBRATION")
    print("=" * 80)
    print(f"Target capacity: {target_capacity_Ah:.2f} Ah")

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
        print(f"  Iteration {iteration + 1}/{MAX_ITERATIONS}...", end=" ", flush=True)

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
            print("Insufficient cycles")
            break

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah

        if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
            print(f"CONVERGED (scale={scale_factor:.6f})")
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
        print(f"Capacity: {discharge_capacity:.2f} Ah (scale={scale_factor:.6f})")

    return default_params, model_options


def run_spmet_energy(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run SPMeT energy analysis with power profile.

    Auto-detects charge/discharge phases from power sign and calculates
    total energy in/out and round-trip efficiency.

    Args:
        cell_design: Cell design parameters dictionary

        simulation_config: Simulation configuration dictionary containing:
            - power_profile: Dict with power profile data (required):
                - time_s: Array of time points [s]
                - power_W: Array of power values [W] (positive=discharge, negative=charge)
                - label: Label for the profile (optional)
            - initial_soc: Initial state of charge [0-1] (default: 0.8)
            - period: Sampling period string (default: "1 second")
            - upper_voltage_cutoff: Upper voltage cutoff [V] (required)
            - lower_voltage_cutoff: Lower voltage cutoff [V] (required)
            - contact_resistance: Contact resistance [Ohm] (required)
            - total_heat_transfer_coefficient: Heat transfer coefficient [W.m-2.K-1] (required)
            - cooling_surface_area: Cell cooling surface area [m2] (required)
            - ambient_temperature: Ambient temperature [K] (required)
            - initial_temperature: Initial temperature [K] (required)

    Returns:
        Dictionary containing:
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
            - charge_phase_indices: Array of indices where power < 0 (charging)
            - discharge_phase_indices: Array of indices where power > 0 (discharging)
            - total_energy_in_Wh: Total energy charged [Wh]
            - total_energy_out_Wh: Total energy discharged [Wh]
            - energy_dissipated_Wh: Total energy dissipated [Wh]
            - round_trip_efficiency: Energy out / Energy in [-]
            - profile_label: Label for this profile
            - success: Boolean indicating if simulation succeeded
            - error: Error message if failed (optional)

    Example:
        >>> power_profile = {
        ...     "time_s": [0, 1800, 3600, 5400],
        ...     "power_W": [-1000, -1000, 1000, 1000],  # charge then discharge
        ...     "label": "charge_discharge_cycle"
        ... }
        >>> config = {
        ...     "power_profile": power_profile,
        ...     "initial_soc": 0.5,
        ...     "upper_voltage_cutoff": 3.65,
        ...     "lower_voltage_cutoff": 2.5,
        ...     "contact_resistance": 1e-5,
        ...     "total_heat_transfer_coefficient": 10.0,
        ...     "cooling_surface_area": 0.1,
        ...     "ambient_temperature": 298.15,
        ...     "initial_temperature": 298.15,
        ... }
        >>> result = run_spmet_energy(cell_design, config)
    """
    # Build parameters (includes calibration)
    default_params, model_options = _build_pybamm_params(cell_design, simulation_config)

    # Get power profile
    power_profile = simulation_config["power_profile"]
    time_s = np.array(power_profile["time_s"])
    power_W = np.array(power_profile["power_W"])
    label = power_profile.get("label")

    print("\n" + "=" * 80)
    print("RUNNING ENERGY ANALYSIS")
    print("=" * 80)
    print(f"  Label: {label}")
    print(f"  Duration: {time_s[-1]:.1f} s ({time_s[-1]/60:.1f} min)")
    print(f"  Power range: {power_W.min():.1f} to {power_W.max():.1f} W")
    print(f"  Data points: {len(time_s)}")

    # Create power step
    power_data = np.column_stack((time_s, power_W))
    power_step = pybamm.step.power(power_data, duration=time_s[-1])

    period = simulation_config.get("period")
    experiment = pybamm.Experiment([power_step], period=period)

    # Setup solver with overpotential variables
    var_pts = {"x_n": 20, "x_s": 20, "x_p": 20, "r_n": 20, "r_p": 20}

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
    model = pybamm.lithium_ion.SPMe(options=model_options)
    model.variables["Anode potential [V]"] = model.variables[
        "Negative electrode surface potential difference at separator interface [V]"
    ]

    # Setup simulation
    sim = pybamm.Simulation(
        model,
        parameter_values=default_params,
        experiment=experiment,
        var_pts=var_pts,
    )

    initial_soc = simulation_config.get("initial_soc")

    try:
        print(f"  Running simulation (initial SOC: {initial_soc*100:.0f}%)...")
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        # Extract time series data
        result = {
            "time_s": solution["Time [s]"].entries,
            "voltage_V": solution["Terminal voltage [V]"].entries,
            "current_A": solution["Current [A]"].entries,
            "temperature_K": solution["Volume-averaged cell temperature [K]"].entries,
            "capacity_Ah": solution["Discharge capacity [A.h]"].entries,
            "energy_Wh": solution["Discharge energy [W.h]"].entries,
            "power_W": solution["Power [W]"].entries,
            "anode_potential_V": solution["Anode potential [V]"].entries,
            "profile_label": label,
            "success": True,
        }

        # Extract overpotentials
        try:
            result["reaction_overpotential_V"] = solution[
                "Sum of x-averaged negative electrode reaction overpotentials [V]"
            ].entries
        except (KeyError, AttributeError):
            pass

        try:
            result["concentration_overpotential_V"] = solution[
                "X-averaged negative electrode concentration overpotential [V]"
            ].entries
        except (KeyError, AttributeError):
            pass

        try:
            result["sei_overpotential_V"] = solution[
                "Negative electrode SEI film overpotential [V]"
            ].entries
        except (KeyError, AttributeError):
            pass

        try:
            result["ohmic_overpotential_V"] = solution["Ohmic losses [V]"].entries
        except (KeyError, AttributeError):
            pass

        # Auto-detect charge/discharge phases from power sign
        power_array = result["power_W"]
        charge_indices = np.where(power_array < 0)[0]
        discharge_indices = np.where(power_array > 0)[0]

        result["charge_phase_indices"] = charge_indices
        result["discharge_phase_indices"] = discharge_indices

        # Calculate energy metrics
        time_array = result["time_s"]
        dt = np.diff(time_array, prepend=time_array[0])

        # Total energy in (charging, power < 0)
        energy_in_W_s = np.sum(np.abs(power_array[charge_indices]) * dt[charge_indices])
        total_energy_in_Wh = energy_in_W_s / 3600.0

        # Total energy out (discharging, power > 0)
        energy_out_W_s = np.sum(power_array[discharge_indices] * dt[discharge_indices])
        total_energy_out_Wh = energy_out_W_s / 3600.0

        # Round-trip efficiency
        if total_energy_in_Wh > 0:
            round_trip_efficiency = total_energy_out_Wh / total_energy_in_Wh
        else:
            round_trip_efficiency = 0.0

        # Energy dissipated
        energy_dissipated_Wh = total_energy_in_Wh - total_energy_out_Wh

        result["total_energy_in_Wh"] = total_energy_in_Wh
        result["total_energy_out_Wh"] = total_energy_out_Wh
        result["energy_dissipated_Wh"] = energy_dissipated_Wh
        result["round_trip_efficiency"] = round_trip_efficiency

        print(f"  Completed: {len(result['time_s'])} data points")
        print(f"  Energy in: {total_energy_in_Wh:.2f} Wh")
        print(f"  Energy out: {total_energy_out_Wh:.2f} Wh")
        print(f"  Round-trip efficiency: {round_trip_efficiency*100:.2f}%")
        print(f"  Energy dissipated: {energy_dissipated_Wh:.2f} Wh")

        return result

    except pybamm.SolverError as e:
        print(f"  Failed: {str(e)[:100]}")
        return {
            "profile_label": label,
            "success": False,
            "error": str(e),
        }
