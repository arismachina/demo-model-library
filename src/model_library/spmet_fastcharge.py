"""
SPMeT Fast Charge Module

Anode-riding fast charge algorithm: CC → Anode Plateau → CV
Prevents lithium plating during high-rate charging by maintaining
anode potential above threshold.
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


def run_spmet_fastcharge(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run SPMeT fast charge with anode-riding algorithm.

    Three-phase charging protocol:
    1. CC (Constant Current): Charge at specified C-rate until anode potential threshold
    2. Anode Riding: Maintain anode potential at threshold (prevents Li plating)
    3. CV (Constant Voltage): Hold at upper voltage until termination current

    Args:
        cell_design: Cell design parameters dictionary

        simulation_config: Simulation configuration dictionary containing:
            - c_rate: Charging C-rate for CC phase (required)
            - anode_potential_threshold_V: Anode potential cutoff [V] (default: 0.02)
            - jelly_roll_temperature_threshold_K: Temperature cutoff [K] (optional)
            - cv_termination_c_rate: Termination C-rate for CV phase (default: 0.05)
            - max_charge_time_s: Maximum total charge time [s] (default: 3600)
            - initial_soc: Initial state of charge [0-1] (default: 0.1)
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
            - phase_labels: Array marking CC/plateau/CV phases (1=CC, 2=plateau, 3=CV)
            - charge_time_s: Total charge time [s]
            - final_soc: Final state of charge
            - success: Boolean indicating if simulation succeeded
            - error: Error message if failed (optional)

    Example:
        >>> config = {
        ...     "c_rate": 5.0,
        ...     "anode_potential_threshold_V": 0.02,
        ...     "cv_termination_c_rate": 0.05,
        ...     "max_charge_time_s": 1800,
        ...     "initial_soc": 0.1,
        ...     "upper_voltage_cutoff": 3.65,
        ...     "lower_voltage_cutoff": 2.5,
        ...     "contact_resistance": 1e-5,
        ...     "total_heat_transfer_coefficient": 10.0,
        ...     "cooling_surface_area": 0.1,
        ...     "ambient_temperature": 298.15,
        ...     "initial_temperature": 298.15,
        ... }
        >>> result = run_spmet_fastcharge(cell_design, config)
    """
    # Build parameters and calibrate
    default_params, model_options = _build_pybamm_params(cell_design, simulation_config)

    # Get configuration
    c_rate = simulation_config["c_rate"]
    anode_threshold = simulation_config.get("anode_potential_threshold_V")
    temp_threshold = simulation_config.get("jelly_roll_temperature_threshold_K")
    upper_voltage = simulation_config["upper_voltage_cutoff"]
    cv_termination = simulation_config.get("cv_termination_c_rate")
    max_time_s = simulation_config.get("max_charge_time_s")
    initial_soc = simulation_config.get("initial_soc")
    period = simulation_config.get("period")

    print("\n" + "=" * 80)
    print("RUNNING FAST CHARGE (ANODE-RIDING)")
    print("=" * 80)
    print(f"  C-rate: {c_rate}C")
    print(f"  Anode threshold: {anode_threshold} V")
    print(f"  Upper voltage: {upper_voltage} V")
    print(f"  CV termination: {cv_termination}C")
    print(f"  Max time: {max_time_s} s")
    print(f"  Initial SOC: {initial_soc*100:.0f}%")

    # Define cutoff functions
    def anode_potential_cutoff(variables):
        return variables["Anode potential [V]"] - anode_threshold

    def temperature_cutoff(variables):
        return temp_threshold - variables["Volume-averaged cell temperature [K]"]

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

    # CV hold with time limit
    cv_hold_step = pybamm.step.voltage(
        upper_voltage,
        duration=max_time_s,
        termination=f"C/{int(1/cv_termination)}",
    )

    # Create three-phase experiment
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

    try:
        print(f"  Running simulation...")
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        # Use full solution (not cycle extraction) for anode-riding
        result = {
            "time_s": solution["Time [s]"].entries,
            "voltage_V": solution["Terminal voltage [V]"].entries,
            "current_A": solution["Current [A]"].entries,
            "temperature_K": solution["Volume-averaged cell temperature [K]"].entries,
            "capacity_Ah": solution["Discharge capacity [A.h]"].entries,
            "energy_Wh": solution["Discharge energy [W.h]"].entries,
            "power_W": solution["Power [W]"].entries,
            "anode_potential_V": solution["Anode potential [V]"].entries,
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

        # Detect phase transitions
        # Phase 1 (CC): High current, anode potential dropping
        # Phase 2 (Anode riding): Anode potential at threshold, current reducing
        # Phase 3 (CV): Voltage at max, current tapering
        current_array = result["current_A"]
        voltage_array = result["voltage_V"]
        anode_array = result["anode_potential_V"]

        phase_labels = np.ones(len(current_array), dtype=int)  # Default to phase 1

        # Simple heuristic: phase changes when voltage reaches upper limit
        # More sophisticated detection could use derivative analysis
        for i in range(len(voltage_array)):
            if voltage_array[i] >= upper_voltage - 0.01:  # Within 10mV of upper limit
                phase_labels[i:] = 3  # CV phase
                break
            elif abs(anode_array[i] - anode_threshold) < 0.005:  # Near anode threshold
                phase_labels[i] = 2  # Anode riding

        result["phase_labels"] = phase_labels
        result["charge_time_s"] = float(result["time_s"][-1])

        # Estimate final SOC (rough approximation from capacity change)
        capacity_change = result["capacity_Ah"][-1] - result["capacity_Ah"][0]
        nominal_capacity = cell_design["nominal_capacity"]["value"]
        soc_change = -capacity_change / nominal_capacity  # Negative current = charging
        result["final_soc"] = min(1.0, initial_soc + soc_change)

        print(f"  Completed: {len(result['time_s'])} data points")
        print(f"  Charge time: {result['charge_time_s']:.1f} s")
        print(f"  Final SOC: {result['final_soc']*100:.1f}%")
        print(f"  Final voltage: {result['voltage_V'][-1]:.3f} V")

        return result

    except pybamm.SolverError as e:
        print(f"  Failed: {str(e)[:100]}")
        return {
            "success": False,
            "error": str(e),
        }
