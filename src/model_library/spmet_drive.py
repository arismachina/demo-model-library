"""
SPMeT Drive Cycle Simulation Module (Standalone)

Runs drive cycle simulations with comprehensive range and energy analysis.
This module is self-contained and does not depend on spmet.py.
"""

import pybamm
import numpy as np


# Known drive cycle distances (km)
DRIVE_CYCLE_DISTANCES = {
    # Automotive cycles
    "Auto WLTP": 23.266,  # WLTP Class 3 full cycle
    "Auto US06": 12.8,  # US06 aggressive driving cycle
    "Track Nurburgring": 20.8,  # Nurburgring Nordschleife
}

# Typical speeds for aerial vehicles (km/h) - used as fallback
AERIAL_SPEEDS = {
    "Aero Quad Drone": 40,
    "Aero UAV": 80,
    "Aero eVTOL": 150,
}


def _build_pybamm_params(cell_design: dict, simulation_config: dict) -> tuple:
    """
    Build PyBaMM parameters from cell design manifest and run capacity calibration.

    Returns:
        Tuple of (calibrated_params, model_options)
    """
    print("\nBuilding model parameters from manifest...")

    # Select base parameter set based on cathode chemistry
    cathode_material = cell_design["positive_electrode"]["coating"]["formulation"][
        "primary_active_material"
    ]["name"]

    if "LFP" in cathode_material.upper():
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
        "Positive electrode thickness [m]": (
            pos_electrode["coating"]["thickness"]["value"] / 1e6
        ),
        "Positive electrode porosity": pos_electrode["coating"]["porosity"]["value"],
        "Positive electrode active material volume fraction": pos_electrode["coating"][
            "active_material_volume_fraction"
        ]["value"],
        "Positive electrode density [kg.m-3]": (
            pos_electrode["coating"]["density"]["value"] * 1000
        ),
    }

    positive_cc_params = {
        "Positive current collector thickness [m]": (
            pos_electrode["foil"]["thickness"]["value"] / 1e6
        ),
    }

    # Negative electrode parameters
    neg_electrode = cell_design["negative_electrode"]

    negative_electrode_params = {
        "Negative electrode thickness [m]": (
            neg_electrode["coating"]["thickness"]["value"] / 1e6
        ),
        "Negative electrode porosity": neg_electrode["coating"]["porosity"]["value"],
        "Negative electrode active material volume fraction": neg_electrode["coating"][
            "active_material_volume_fraction"
        ]["value"],
        "Negative electrode density [kg.m-3]": (
            neg_electrode["coating"]["density"]["value"] * 1000
        ),
    }

    negative_cc_params = {
        "Negative current collector thickness [m]": (
            neg_electrode["foil"]["thickness"]["value"] / 1e6
        ),
    }

    # Separator parameters
    separator = cell_design["separator"]
    separator_params = {
        "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
        "Separator porosity": separator["porosity"]["value"],
        "Separator density [kg.m-3]": (
            separator["material"]["physical_properties"]["density"]["value"] * 1000
        ),
    }

    # Thermal parameters
    thermal_params = {
        "Reference temperature [K]": 298.15,
        "Total heat transfer coefficient [W.m-2.K-1]": simulation_config[
            "total_heat_transfer_coefficient_W_m2K"
        ],
        "Cell cooling surface area [m2]": simulation_config["cooling_surface_area_m2"],
        "Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
    }

    # Operating conditions
    operating_conditions = {
        "Ambient temperature [K]": simulation_config["ambient_temperature_K"],
        "Initial temperature [K]": simulation_config["initial_temperature_K"],
        "Contact resistance [Ohm]": simulation_config["contact_resistance_Ohm"],
        "Upper voltage cut-off [V]": simulation_config["upper_voltage_cutoff_V"],
        "Lower voltage cut-off [V]": simulation_config["lower_voltage_cutoff_V"],
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

    # Model options
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    # Capacity calibration
    target_capacity_Ah = cell_design["nominal_capacity"]["value"]

    charge_step = (
        f"Charge at 0.1C until {cell_design['upper_voltage_cutoff']['value']} V"
    )
    hold_step = f"Hold at {cell_design['upper_voltage_cutoff']['value']} V for 2 hours or until C/50"
    discharge_step = f"Discharge at 0.1C for 15 hours or until {cell_design['lower_voltage_cutoff']['value']} V"

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


def _run_pybamm_spmet_drivecycle(
    drive_cycle: dict,
    simulation_config: dict,
    default_params: pybamm.ParameterValues,
    model_options: dict,
) -> dict:
    """
    Execute PyBaMM simulation for drive cycle.

    Returns:
        Dict with simulation results or error
    """
    print("\n" + "=" * 80)
    print("RUNNING DRIVE CYCLE")
    print("=" * 80)

    time_s = np.array(drive_cycle["time_s"])
    label = drive_cycle.get("label", "drive_cycle")

    # Get custom termination thresholds from config
    anode_threshold = simulation_config.get("anode_potential_threshold_V")
    temp_threshold = simulation_config.get("temperature_threshold_K")
    lower_voltage = simulation_config.get("lower_voltage_cutoff_V")
    upper_voltage = simulation_config.get("upper_voltage_cutoff_V")

    # Build termination conditions list
    termination_conditions = []

    if anode_threshold is not None:

        def anode_potential_cutoff(variables):
            return variables["Anode potential [V]"] - anode_threshold

        termination_conditions.append(
            pybamm.step.CustomTermination(
                "Anode potential cut-off [V]", anode_potential_cutoff
            )
        )

    if temp_threshold is not None:

        def temperature_cutoff(variables):
            return temp_threshold - variables["Volume-averaged cell temperature [K]"]

        termination_conditions.append(
            pybamm.step.CustomTermination("Temperature cut-off [K]", temperature_cutoff)
        )

    if lower_voltage is not None:

        def voltage_lower_cutoff(variables):
            return variables["Terminal voltage [V]"] - lower_voltage

        termination_conditions.append(
            pybamm.step.CustomTermination(
                "Lower voltage cut-off [V]", voltage_lower_cutoff
            )
        )

    if upper_voltage is not None:

        def voltage_upper_cutoff(variables):
            return upper_voltage - variables["Terminal voltage [V]"]

        termination_conditions.append(
            pybamm.step.CustomTermination(
                "Upper voltage cut-off [V]", voltage_upper_cutoff
            )
        )

    # Determine drive cycle type: power_W or c_rate
    if "power_W" in drive_cycle:
        values = np.array(drive_cycle["power_W"])
        print(f"  Type: Power")
        print(f"  Power range: {values.min():.1f} to {values.max():.1f} W")
        drive_data = np.column_stack((time_s, values))
        if termination_conditions:
            drive_cycle_step = pybamm.step.power(
                drive_data, duration=time_s[-1], termination=termination_conditions
            )
        else:
            drive_cycle_step = pybamm.step.power(drive_data, duration=time_s[-1])
    elif "c_rate" in drive_cycle:
        values = np.array(drive_cycle["c_rate"])
        print(f"  Type: C-rate")
        print(f"  C-rate range: {values.min():.3f} to {values.max():.3f} C")
        drive_data = np.column_stack((time_s, values))
        if termination_conditions:
            drive_cycle_step = pybamm.step.c_rate(
                drive_data, duration=time_s[-1], termination=termination_conditions
            )
        else:
            drive_cycle_step = pybamm.step.c_rate(drive_data, duration=time_s[-1])
    else:
        raise ValueError("drive_cycle must contain either 'power_W' or 'c_rate'")

    print(f"  Label: {label}")
    print(f"  Duration: {time_s[-1]:.1f} s ({time_s[-1]/60:.1f} min)")
    print(f"  Data points: {len(time_s)}")
    if termination_conditions:
        print(f"  Custom terminations: {len(termination_conditions)}")

    period = simulation_config.get("period", "1 second")
    experiment = pybamm.Experiment([drive_cycle_step], period=period)

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
            "Terminal power [W]",
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

    initial_soc = simulation_config.get("initial_soc", 0.8)

    try:
        print(f"  Running simulation (initial SOC: {initial_soc*100:.0f}%)...")
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        termination_reason = getattr(solution, "termination", "completed")

        # Try to extract variables, handling missing ones gracefully
        try:
            discharge_capacity = solution["Discharge capacity [A.h]"].entries
            soc = (
                initial_soc
                - discharge_capacity / default_params["Nominal cell capacity [A.h]"]
            )
        except (KeyError, AttributeError) as e:
            print(f"  Warning: Could not compute SOC - {str(e)[:50]}")
            discharge_capacity = None
            soc = None

        # Build result dict with available data
        result = {
            "experiment_label": label,
            "termination_reason": termination_reason,
            "success": True,
        }

        # Add variables that are available
        try:
            result["time_s"] = solution["Time [s]"].entries
        except (KeyError, AttributeError):
            pass

        try:
            result["voltage_V"] = solution["Terminal voltage [V]"].entries
        except (KeyError, AttributeError):
            pass

        try:
            result["current_A"] = solution["Current [A]"].entries
        except (KeyError, AttributeError):
            pass

        try:
            result["temperature_K"] = solution[
                "Volume-averaged cell temperature [K]"
            ].entries
        except (KeyError, AttributeError):
            pass

        if discharge_capacity is not None:
            result["capacity_Ah"] = discharge_capacity

        try:
            result["energy_Wh"] = solution["Discharge energy [W.h]"].entries
        except (KeyError, AttributeError):
            pass

        try:
            result["power_W"] = solution["Terminal power [W]"].entries
        except (KeyError, AttributeError):
            pass

        if soc is not None:
            result["soc"] = soc

        try:
            result["anode_potential_V"] = solution["Anode potential [V]"].entries
        except (KeyError, AttributeError):
            pass

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

        n_points = len(result.get("time_s", []))
        print(f"  Completed: {n_points} data points")
        if termination_reason != "completed" and termination_reason != "final time":
            print(f"  Termination: {termination_reason}")

        # Check if we got enough data to be useful
        if n_points == 0 or "voltage_V" not in result:
            result["success"] = False
            result["error"] = "Simulation produced insufficient data"
            print("  Warning: Insufficient simulation data")

        return result

    except pybamm.SolverError as e:
        print(f"  Failed: {str(e)[:100]}")
        return {
            "experiment_label": label,
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        print(f"  Unexpected error: {str(e)[:100]}")
        return {
            "experiment_label": label,
            "success": False,
            "error": f"Unexpected error: {str(e)}",
        }


def estimate_speed_from_power(
    power_W: np.ndarray,
    vehicle_params: dict,
    vehicle_type: str = "ground",
) -> tuple[np.ndarray, dict]:
    """
    Estimate vehicle speed from mechanical power using physics models.

    For ground vehicles: P = F_total * v = (F_drag + F_rolling) * v
        F_drag = 0.5 * rho * Cd * A * v²
        F_rolling = Crr * m * g

    For aircraft: P = (D + W/L_D) * v  where D = 0.5 * rho * Cd * A * v²
        In steady cruise, Lift = Weight, so we use L/D ratio or Cd

    Args:
        power_W: Array of mechanical power values [W]
        vehicle_params: Dict with vehicle parameters:
            - weight_kg: Vehicle weight [kg]
            - drag_coefficient: Cd
            - frontal_area_m2: Reference area [m²]
            - drivetrain_efficiency: Efficiency (0-1), default 0.85
            - air_density_kg_m3: Air density, default 1.225
            - rolling_resistance: Crr for ground vehicles, default 0.01
            - lift_to_drag: L/D ratio for aircraft (optional)
        vehicle_type: "ground" or "aircraft"

    Returns:
        Tuple of (speed_m_s array, metadata dict)
    """
    # Extract parameters with defaults
    weight_kg = vehicle_params["weight_kg"]
    Cd = vehicle_params.get("drag_coefficient", 0.3)
    A = vehicle_params.get("frontal_area_m2", 2.0)
    eta = vehicle_params.get("drivetrain_efficiency", 0.85)
    rho = vehicle_params.get("air_density_kg_m3", 1.225)
    Crr = vehicle_params.get("rolling_resistance", 0.01)
    L_D = vehicle_params.get("lift_to_drag", None)

    g = 9.81  # m/s²
    W = weight_kg * g  # Weight force [N]

    # Mechanical power at wheels/propeller
    P_mech = np.abs(power_W) * eta

    # Pre-compute drag coefficient term
    drag_coef = 0.5 * rho * Cd * A

    speeds = np.zeros_like(power_W, dtype=float)

    for i, P in enumerate(P_mech):
        if P <= 0:
            speeds[i] = 0
            continue

        if vehicle_type == "ground":
            # Ground vehicle: P = (drag_coef * v² + Crr * W) * v
            # Cubic equation: drag_coef * v³ + Crr * W * v - P = 0
            F_roll = Crr * W
            coeffs = [drag_coef, 0, F_roll, -P]
            roots = np.roots(coeffs)
            real_positive = [r.real for r in roots if np.isreal(r) and r.real > 0]
            speeds[i] = real_positive[0] if real_positive else 0

        else:  # aircraft
            if L_D is not None:
                # Aircraft with known L/D: P = W * v / L_D + drag_coef * v³
                coeffs = [drag_coef, 0, W / L_D, -P]
                roots = np.roots(coeffs)
                real_positive = [r.real for r in roots if np.isreal(r) and r.real > 0]
                speeds[i] = real_positive[0] if real_positive else 0
            else:
                # Simplified: P = drag_coef * v³
                if drag_coef > 0:
                    speeds[i] = (P / drag_coef) ** (1 / 3)
                else:
                    speeds[i] = 0

    # Calculate metadata
    valid_speeds = speeds[speeds > 0]
    metadata = {
        "avg_speed_m_s": float(np.mean(valid_speeds)) if len(valid_speeds) > 0 else 0,
        "max_speed_m_s": float(np.max(speeds)),
        "avg_speed_kmh": (
            float(np.mean(valid_speeds) * 3.6) if len(valid_speeds) > 0 else 0
        ),
        "max_speed_kmh": float(np.max(speeds) * 3.6),
        "vehicle_type": vehicle_type,
    }

    return speeds, metadata


def run_spmet_drivecycle(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run a drive cycle simulation with comprehensive analysis.

    This is a standalone function that handles:
    1. PyBaMM parameter setup from cell design
    2. Capacity calibration
    3. Drive cycle simulation
    4. Energy and range analysis

    Args:
        cell_design: Cell design parameters dictionary (from manifest)
        simulation_config: Simulation configuration containing:
            - ambient_temperature_K: Ambient temperature [K]
            - initial_temperature_K: Initial cell temperature [K]
            - initial_soc: Initial state of charge [0-1]
            - upper_voltage_cutoff_V: Upper voltage limit [V]
            - lower_voltage_cutoff_V: Lower voltage limit [V]
            - contact_resistance_Ohm: Contact resistance [Ohm]
            - total_heat_transfer_coefficient_W_m2K: Heat transfer coeff [W/m2K]
            - cooling_surface_area_m2: Cooling surface area [m2]
            - period: Sampling period string (default: "1 second")
            - drive_cycle: Dict with drive cycle data:
                - time_s: Array of time points [s]
                - c_rate: Array of C-rate values (positive = discharge), OR
                - power_W: Array of power values [W] (positive = discharge)
                - label: Label for the drive cycle
                - distance_km: (optional) Distance covered in one cycle [km]
            - min_soc: Minimum SOC for range calculation (default: 0.10)
            - max_soc: Maximum SOC for range calculation (default: 0.90)
            - anode_potential_threshold_V: (optional) Terminate if anode potential drops below this [V]
            - temperature_threshold_K: (optional) Terminate if temperature exceeds this [K]
            - vehicle_params: (optional) Dict for range estimation from power:
                - weight_kg: Vehicle weight including battery [kg]
                - drag_coefficient: Aerodynamic drag coefficient Cd
                - frontal_area_m2: Frontal/reference area [m²]
                - drivetrain_efficiency: Drivetrain/propeller efficiency (0-1)
                - air_density_kg_m3: Air density (default: 1.225)
                - rolling_resistance: Rolling resistance coeff (ground vehicles)
                - lift_to_drag: L/D ratio (aircraft, optional)
            - pack_max_energy_kWh: (optional)
            - pack_nominal_voltage_V: (optional)
            - pack_rated_peak_power_kW: (optional)

    Returns:
        Dictionary containing:
            - success: Boolean indicating simulation success
            - error: Error message if failed
            - timeseries: Dict with time series arrays
            - summary: Dict with simulation summary
            - energy_analysis: Dict with energy metrics
            - range_analysis: Dict with range estimates
            - config: Original simulation config
    """
    # Validate inputs
    if "drive_cycle" not in simulation_config:
        raise ValueError("simulation_config must contain 'drive_cycle'")

    drive_cycle = simulation_config["drive_cycle"]
    if "time_s" not in drive_cycle:
        raise ValueError("drive_cycle must contain 'time_s'")
    if "c_rate" not in drive_cycle and "power_W" not in drive_cycle:
        raise ValueError("drive_cycle must contain either 'c_rate' or 'power_W'")

    # Get cell parameters
    cell_nominal_capacity = cell_design["nominal_capacity"]["value"]
    cell_nominal_energy = cell_design.get("nominal_energy", {}).get("value")
    cell_nominal_voltage = cell_design.get("nominal_voltage", {}).get("value")

    # Handle pack-to-cell power conversion
    pack_energy_kWh = simulation_config.get("pack_max_energy_kWh", None)
    pack_max_power_kW = simulation_config.get("pack_rated_peak_power_kW")
    pack_nominal_voltage = simulation_config.get("pack_nominal_voltage_V")

    if pack_energy_kWh is not None and "power_W" in drive_cycle:
        cells_series = pack_nominal_voltage / cell_nominal_voltage
        cells_parallel = (
            pack_energy_kWh * 1000 / (pack_nominal_voltage * cell_nominal_capacity)
        )
        total_cells = cells_series * cells_parallel

        pack_power_W = np.array(drive_cycle["power_W"])
        cell_power_W = pack_power_W / total_cells

        drive_cycle = {**drive_cycle, "power_W": cell_power_W}
        simulation_config = {**simulation_config, "drive_cycle": drive_cycle}

        print(
            f"\n  Pack config: {cells_series:.0f}S{cells_parallel:.0f}P ({total_cells:.0f} cells)"
        )
        print(
            f"  Pack power range: {pack_power_W.min():.1f} to {pack_power_W.max():.1f} W"
        )
        print(
            f"  Cell power range: {cell_power_W.min():.1f} to {cell_power_W.max():.1f} W"
        )

    # Build PyBaMM parameters and run capacity calibration
    default_params, model_options = _build_pybamm_params(cell_design, simulation_config)

    # Run simulation
    sim_result = _run_pybamm_spmet_drivecycle(
        drive_cycle=drive_cycle,
        simulation_config=simulation_config,
        default_params=default_params,
        model_options=model_options,
    )

    if not sim_result.get("success", False):
        return {
            "success": False,
            "error": sim_result.get("error", "Unknown error"),
            "config": simulation_config,
        }

    # Extract time series
    timeseries = {
        "time_s": sim_result["time_s"],
        "voltage_V": sim_result["voltage_V"],
        "current_A": sim_result["current_A"],
        "power_W": sim_result["power_W"],
        "temperature_K": sim_result["temperature_K"],
        "capacity_Ah": sim_result["capacity_Ah"],
        "soc": sim_result["soc"],
        "energy_Wh": sim_result["energy_Wh"],
        "anode_potential_V": sim_result["anode_potential_V"],
    }

    # Capture termination reason
    termination_reason = sim_result.get("termination_reason", "completed")

    # Calculate summary statistics
    sim_time = sim_result["time_s"]
    sim_voltage = sim_result["voltage_V"]
    sim_current = sim_result["current_A"]
    sim_power = sim_result["power_W"]
    sim_temp = sim_result["temperature_K"]
    sim_capacity = sim_result["capacity_Ah"]

    summary = {
        "duration_s": float(sim_time[-1] - sim_time[0]),
        "duration_min": float((sim_time[-1] - sim_time[0]) / 60),
        "voltage_min_V": float(sim_voltage.min()),
        "voltage_max_V": float(sim_voltage.max()),
        "current_min_A": float(sim_current.min()),
        "current_max_A": float(sim_current.max()),
        "power_min_W": float(sim_power.min()),
        "power_max_W": float(sim_power.max()),
        "temperature_min_C": float(sim_temp.min() - 273.15),
        "temperature_max_C": float(sim_temp.max() - 273.15),
        "temperature_rise_C": float(sim_temp.max() - sim_temp[0]),
        "data_points": len(sim_time),
    }

    # Energy analysis
    dt = np.diff(sim_time)
    power_mid = (sim_power[:-1] + sim_power[1:]) / 2

    discharge_mask = power_mid > 0
    regen_mask = power_mid < 0

    energy_discharged = float(
        np.sum(power_mid[discharge_mask] * dt[discharge_mask]) / 3600
    )
    energy_regen = float(-np.sum(power_mid[regen_mask] * dt[regen_mask]) / 3600)
    energy_net = energy_discharged - energy_regen

    capacity_used = float(sim_capacity[-1] - sim_capacity[0])
    initial_soc = simulation_config.get("initial_soc", 0.8)
    soc_change = capacity_used / cell_nominal_capacity * 100

    energy_analysis = {
        "energy_discharged_Wh": energy_discharged,
        "energy_regenerated_Wh": energy_regen,
        "energy_net_Wh": energy_net,
        "capacity_used_Ah": capacity_used,
        "soc_change_pct": soc_change,
        "regeneration_ratio_pct": (
            energy_regen / energy_discharged * 100 if energy_discharged > 0 else 0
        ),
    }

    # Range analysis
    cycle_duration_s = summary["duration_s"]
    label = drive_cycle.get("label", "drive_cycle")

    # Check for vehicle parameters to calculate speed from power
    # Support both new individual params and legacy vehicle_params dict
    vehicle_params = simulation_config.get("vehicle_params")
    has_vehicle_params = (
        vehicle_params is not None or "vehicle_weight_kg" in simulation_config
    )

    # Build vehicle_params dict from individual parameters if provided
    if vehicle_params is None and "vehicle_weight_kg" in simulation_config:
        vehicle_params = {
            "weight_kg": simulation_config["vehicle_weight_kg"],
            "drag_coefficient": simulation_config.get("vehicle_drag_coefficient", 0.3),
            "frontal_area_m2": simulation_config.get("vehicle_frontal_area_m2", 2.0),
            "rolling_resistance": simulation_config.get(
                "vehicle_rolling_resistance", 0.01
            ),
            "drivetrain_efficiency": simulation_config.get(
                "vehicle_drivetrain_efficiency", 0.85
            ),
        }

    speed_timeseries = None
    speed_metadata = None
    physics_distance_km = None

    # Determine cycle distance from drive_cycle data
    cycle_distance_km = drive_cycle.get("distance_km")
    is_aerial = label.startswith("Aero") if cycle_distance_km is None else False

    # Always calculate speed from vehicle physics when vehicle_params provided
    if has_vehicle_params and vehicle_params is not None:
        power_for_vehicle = pack_power_W if pack_power_W is not None else sim_power
        vehicle_type = "aircraft" if is_aerial else "ground"
        speed_timeseries, speed_metadata = estimate_speed_from_power(
            power_for_vehicle, vehicle_params, vehicle_type
        )

        speed_mid = (speed_timeseries[:-1] + speed_timeseries[1:]) / 2
        distance_m = float(np.sum(speed_mid * dt))
        physics_distance_km = distance_m / 1000

        # Use physics-based distance if not provided in drive_cycle
        if cycle_distance_km is None:
            cycle_distance_km = physics_distance_km

    if cycle_distance_km is None:
        cycle_distance_km = DRIVE_CYCLE_DISTANCES.get(label)

    if cycle_distance_km is None and label in AERIAL_SPEEDS:
        avg_speed_kmh = AERIAL_SPEEDS[label]
        cycle_distance_km = avg_speed_kmh * (cycle_duration_s / 3600)
        is_aerial = True

    # SOC limits for range calculation
    min_soc = simulation_config.get("min_soc", 0.10)
    max_soc = simulation_config.get("max_soc", 0.90)

    available_capacity = cell_nominal_capacity * (initial_soc - min_soc)
    usable_capacity = cell_nominal_capacity * (max_soc - min_soc)

    cycles_possible = available_capacity / capacity_used if capacity_used > 0 else 0
    full_charge_cycles = usable_capacity / capacity_used if capacity_used > 0 else 0

    range_analysis = {
        "cycle_label": label,
        "cycle_duration_s": cycle_duration_s,
        "cycle_distance_km": cycle_distance_km,
        "is_aerial": is_aerial,
        "initial_soc": initial_soc,
        "min_soc": min_soc,
        "max_soc": max_soc,
        "available_capacity_Ah": available_capacity,
        "usable_capacity_Ah": usable_capacity,
        "capacity_per_cycle_Ah": capacity_used,
        "energy_per_cycle_Wh": energy_net,
        "cycles_possible": cycles_possible,
    }

    # Add distance-based metrics if available
    if cycle_distance_km and cycle_distance_km > 0:
        range_km = cycles_possible * cycle_distance_km
        full_range_km = full_charge_cycles * cycle_distance_km
        avg_speed_kmh = cycle_distance_km / cycle_duration_s * 3600

        range_analysis.update(
            {
                "avg_speed_kmh": avg_speed_kmh,
                "energy_per_km_Wh": energy_net / cycle_distance_km,
                "capacity_per_km_Ah": capacity_used / cycle_distance_km,
                "range_km": range_km,
                "range_miles": range_km * 0.621371,
                "full_charge_range_km": full_range_km,
                "full_charge_range_miles": full_range_km * 0.621371,
            }
        )

    # Time-based metrics
    drive_time_s = cycles_possible * cycle_duration_s
    full_charge_time_s = full_charge_cycles * cycle_duration_s

    time_label = "flight" if is_aerial else "drive"
    range_analysis.update(
        {
            f"{time_label}_time_min": drive_time_s / 60,
            f"{time_label}_time_hr": drive_time_s / 3600,
            f"full_charge_{time_label}_time_min": full_charge_time_s / 60,
            f"full_charge_{time_label}_time_hr": full_charge_time_s / 3600,
        }
    )

    # Add pack configuration if provided
    if pack_energy_kWh is not None:
        cells_series = int(np.ceil(pack_nominal_voltage / cell_nominal_voltage))
        cell_nominal_energy = cell_design.get("nominal_energy", {}).get("value")
        if cell_nominal_energy is None:
            cell_nominal_energy = cell_nominal_capacity * cell_nominal_voltage
        cells_parallel = int(
            np.ceil(
                pack_energy_kWh * 1000 / (pack_nominal_voltage * cell_nominal_capacity)
            )
        )
        total_cells = cells_series * cells_parallel

        range_analysis["pack_config"] = {
            "cells_in_series": cells_series,
            "cells_in_parallel": cells_parallel,
            "total_cells": total_cells,
            "pack_energy_kWh": pack_energy_kWh,
            "pack_voltage_nominal_V": pack_nominal_voltage,
        }

        range_analysis["pack_range_km"] = (
            range_analysis.get("range_km", 0) * cells_parallel
        )
        range_analysis["pack_full_charge_range_km"] = (
            range_analysis.get("full_charge_range_km", 0) * cells_parallel
        )

    # Add vehicle physics analysis if calculated
    if speed_metadata is not None:
        range_analysis["vehicle_physics"] = {
            "vehicle_type": speed_metadata["vehicle_type"],
            "avg_speed_kmh": speed_metadata["avg_speed_kmh"],
            "max_speed_kmh": speed_metadata["max_speed_kmh"],
            "physics_distance_km": physics_distance_km,
            "weight_kg": vehicle_params.get("weight_kg"),
            "drag_coefficient": vehicle_params.get("drag_coefficient"),
            "frontal_area_m2": vehicle_params.get("frontal_area_m2"),
            "rolling_resistance": vehicle_params.get("rolling_resistance", 0.01),
            "drivetrain_efficiency": vehicle_params.get("drivetrain_efficiency", 0.85),
        }
        # Add comparison if actual distance was provided
        if (
            drive_cycle.get("distance_km") is not None
            and physics_distance_km is not None
        ):
            actual_distance = drive_cycle["distance_km"]
            range_analysis["vehicle_physics"]["actual_distance_km"] = actual_distance
            range_analysis["vehicle_physics"]["distance_error_pct"] = (
                (physics_distance_km - actual_distance) / actual_distance * 100
            )

    # Add speed to timeseries if calculated
    if speed_timeseries is not None:
        timeseries["speed_m_s"] = speed_timeseries
        timeseries["speed_kmh"] = speed_timeseries * 3.6

    return {
        "success": True,
        "timeseries": timeseries,
        "summary": summary,
        "energy_analysis": energy_analysis,
        "range_analysis": range_analysis,
        "termination_reason": termination_reason,
        "config": simulation_config,
    }
