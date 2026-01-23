"""
SPMeT Drive Cycle Simulation Module

Runs drive cycle simulations and returns comprehensive results including
time series data and range/energy analysis.
"""

import numpy as np
from .spmet import run_spmet


# Known drive cycle distances (km)
DRIVE_CYCLE_DISTANCES = {
    # Automotive cycles
    "Auto WLTP": 23.266,        # WLTP Class 3 full cycle
    "Auto US06": 12.8,          # US06 aggressive driving cycle
    "Track Nurburgring": 20.8,  # Nurburgring Nordschleife
}

# Typical speeds for aerial vehicles (km/h) - used as fallback
AERIAL_SPEEDS = {
    "Aero Quad Drone": 40,
    "Aero UAV": 80,
    "Aero eVTOL": 150,
}

# Typical aerodynamic parameters for drones
DRONE_DEFAULTS = {
    "Aero Quad Drone": {
        "drag_coefficient": 1.0,      # Cd for quadcopter
        "frontal_area_m2": 0.05,      # Typical small drone
        "propeller_efficiency": 0.7,  # Prop efficiency
    },
    "Aero UAV": {
        "drag_coefficient": 0.3,      # Cd for fixed-wing
        "frontal_area_m2": 0.2,       # Medium UAV
        "propeller_efficiency": 0.8,
    },
    "Aero eVTOL": {
        "drag_coefficient": 0.4,      # Cd for eVTOL in cruise
        "frontal_area_m2": 2.0,       # Large aircraft
        "propeller_efficiency": 0.85,
    },
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

            # Solve cubic using numpy roots
            # drag_coef * v³ + 0 * v² + F_roll * v - P = 0
            coeffs = [drag_coef, 0, F_roll, -P]
            roots = np.roots(coeffs)

            # Take the real positive root
            real_positive = [r.real for r in roots if np.isreal(r) and r.real > 0]
            speeds[i] = real_positive[0] if real_positive else 0

        else:  # aircraft
            if L_D is not None:
                # Aircraft with known L/D: P = W * v / L_D + drag_coef * v³
                # This is also cubic: drag_coef * v³ + (W/L_D) * v - P = 0
                coeffs = [drag_coef, 0, W / L_D, -P]
                roots = np.roots(coeffs)
                real_positive = [r.real for r in roots if np.isreal(r) and r.real > 0]
                speeds[i] = real_positive[0] if real_positive else 0
            else:
                # Simplified: assume power overcomes drag only at cruise
                # P = drag_coef * v³, so v = (P / drag_coef)^(1/3)
                # Plus induced drag for lift: P_induced ≈ W² / (2 * rho * v * S * pi * AR * e)
                # Simplified: use P = drag_coef * v³ as approximation
                if drag_coef > 0:
                    speeds[i] = (P / drag_coef) ** (1/3)
                else:
                    speeds[i] = 0

    # Calculate metadata
    valid_speeds = speeds[speeds > 0]
    metadata = {
        "avg_speed_m_s": float(np.mean(valid_speeds)) if len(valid_speeds) > 0 else 0,
        "max_speed_m_s": float(np.max(speeds)),
        "avg_speed_kmh": float(np.mean(valid_speeds) * 3.6) if len(valid_speeds) > 0 else 0,
        "max_speed_kmh": float(np.max(speeds) * 3.6),
        "vehicle_type": vehicle_type,
    }

    return speeds, metadata


def run_drive_cycle(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run a drive cycle simulation with comprehensive analysis.

    Args:
        cell_design: Cell design parameters dictionary (from manifest)
        simulation_config: Simulation configuration containing:
            - ambient_temperature: Ambient temperature [K]
            - initial_temperature: Initial cell temperature [K]
            - initial_soc: Initial state of charge [0-1]
            - upper_voltage_cutoff: Upper voltage limit [V]
            - lower_voltage_cutoff: Lower voltage limit [V]
            - contact_resistance: Contact resistance [Ohm]
            - total_heat_transfer_coefficient: Heat transfer coeff [W/m2K]
            - cooling_surface_area: Cooling surface area [m2]
            - period: Sampling period string (default: "1 second")
            - drive_cycle: Dict with drive cycle data:
                - time_s: Array of time points [s]
                - c_rate: Array of C-rate values (positive = discharge), OR
                - power_W: Array of power values [W] (positive = discharge)
                - label: Label for the drive cycle
                - distance_km: (optional) Distance covered in one cycle [km]
            - min_soc: Minimum SOC for range calculation (default: 0.10)
            - max_soc: Maximum SOC for range calculation (default: 0.90)
            - vehicle_params: (optional) Dict for range estimation from power profile:
                - weight_kg: Vehicle weight including battery [kg]
                - drag_coefficient: Aerodynamic drag coefficient Cd
                - frontal_area_m2: Frontal/reference area [m²]
                - drivetrain_efficiency: Drivetrain/propeller efficiency (0-1)
                - air_density_kg_m3: Air density (default: 1.225)
                - rolling_resistance: Rolling resistance coeff (ground vehicles)
                - lift_to_drag: L/D ratio (aircraft, optional - uses Cd if not provided)
            - pack_config: (optional) Dict to convert pack power to cell power:
                - cells_in_series: Number of cells in series
                - cells_in_parallel: Number of cells in parallel
                If provided, drive_cycle power_W is divided by cells_in_parallel
                to get per-cell power for simulation

    Returns:
        Dictionary containing:
            - success: Boolean indicating simulation success
            - error: Error message if failed
            - timeseries: Dict with time series arrays:
                - time_s, voltage_V, current_A, power_W, temperature_K,
                  capacity_Ah, energy_Wh, anode_potential_V
            - summary: Dict with simulation summary:
                - duration_s, voltage_min/max, current_min/max, etc.
            - energy_analysis: Dict with energy metrics:
                - energy_discharged_Wh, energy_regenerated_Wh, energy_net_Wh,
                  capacity_used_Ah, soc_change_pct, regeneration_ratio_pct
            - range_analysis: Dict with range estimates:
                - cycle_distance_km, energy_per_km_Wh, cycles_possible,
                  range_km, range_miles, drive_time_min, is_aerial,
                  full_charge_range_km, full_charge_time_min
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

    # Handle pack-to-cell power conversion
    pack_config = simulation_config.get("pack_config")
    pack_power_W = None  # Store original pack power for range calculation

    if pack_config is not None and "power_W" in drive_cycle:
        cells_series = pack_config.get("cells_in_series", 1)
        cells_parallel = pack_config.get("cells_in_parallel", 1)
        total_cells = cells_series * cells_parallel

        # Store original pack power for vehicle range calculation
        pack_power_W = np.array(drive_cycle["power_W"])

        # Convert pack power to cell power
        # Pack power splits across parallel strings, each cell in a string sees same current
        # P_cell = P_pack / n_parallel
        cell_power_W = pack_power_W / cells_parallel

        # Update drive_cycle with cell-level power
        drive_cycle = {**drive_cycle, "power_W": cell_power_W}
        simulation_config = {**simulation_config, "drive_cycle": drive_cycle}

        print(f"\n  Pack config: {cells_series}S{cells_parallel}P ({total_cells} cells)")
        print(f"  Pack power range: {pack_power_W.min():.1f} to {pack_power_W.max():.1f} W")
        print(f"  Cell power range: {cell_power_W.min():.1f} to {cell_power_W.max():.1f} W")

    # Get cell parameters
    nominal_capacity = cell_design["nominal_capacity"]["value"]
    nominal_energy = cell_design.get("nominal_energy", {}).get("value")
    if nominal_energy is None:
        # Estimate from capacity and average voltage
        avg_voltage = (
            cell_design["upper_voltage_cutoff"]["value"]
            + cell_design["lower_voltage_cutoff"]["value"]
        ) / 2
        nominal_energy = nominal_capacity * avg_voltage

    # Run simulation
    results = run_spmet(cell_design=cell_design, simulation_config=simulation_config)

    if not results or not results[0].get("success", False):
        error_msg = results[0].get("error", "Unknown error") if results else "No results"
        return {
            "success": False,
            "error": error_msg,
            "config": simulation_config,
        }

    result = results[0]

    # Extract time series
    timeseries = {
        "time_s": result["time_s"],
        "voltage_V": result["voltage_V"],
        "current_A": result["current_A"],
        "power_W": result["power_W"],
        "temperature_K": result["temperature_K"],
        "capacity_Ah": result["capacity_Ah"],
        "energy_Wh": result["energy_Wh"],
        "anode_potential_V": result["anode_potential_V"],
    }

    # Calculate summary statistics
    sim_time = result["time_s"]
    sim_voltage = result["voltage_V"]
    sim_current = result["current_A"]
    sim_power = result["power_W"]
    sim_temp = result["temperature_K"]
    sim_capacity = result["capacity_Ah"]
    sim_energy = result["energy_Wh"]

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

    energy_discharged = float(np.sum(power_mid[discharge_mask] * dt[discharge_mask]) / 3600)
    energy_regen = float(-np.sum(power_mid[regen_mask] * dt[regen_mask]) / 3600)
    energy_net = energy_discharged - energy_regen

    capacity_used = float(sim_capacity[-1] - sim_capacity[0])
    initial_soc = simulation_config.get("initial_soc", 0.8)
    soc_change = capacity_used / nominal_capacity * 100

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

    # Check for vehicle_params to estimate distance from power
    vehicle_params = simulation_config.get("vehicle_params")
    speed_timeseries = None
    speed_metadata = None

    # Determine cycle distance
    cycle_distance_km = drive_cycle.get("distance_km")
    is_aerial = label.startswith("Aero") if cycle_distance_km is None else False

    if cycle_distance_km is None and vehicle_params is not None:
        # Estimate speed and distance from power using vehicle physics
        # Use pack power if available (for vehicle-level calculation), else cell power
        power_for_vehicle = pack_power_W if pack_power_W is not None else sim_power
        vehicle_type = "aircraft" if is_aerial else "ground"
        speed_timeseries, speed_metadata = estimate_speed_from_power(
            power_for_vehicle, vehicle_params, vehicle_type
        )

        # Calculate distance by integrating speed over time
        # Use trapezoidal integration
        speed_mid = (speed_timeseries[:-1] + speed_timeseries[1:]) / 2
        distance_m = float(np.sum(speed_mid * dt))
        cycle_distance_km = distance_m / 1000

    if cycle_distance_km is None:
        # Try to get from known cycles
        cycle_distance_km = DRIVE_CYCLE_DISTANCES.get(label)

    if cycle_distance_km is None and label in AERIAL_SPEEDS:
        # Aerial vehicle - calculate from assumed speed (fallback)
        avg_speed_kmh = AERIAL_SPEEDS[label]
        cycle_distance_km = avg_speed_kmh * (cycle_duration_s / 3600)
        is_aerial = True

    # SOC limits for range calculation
    min_soc = simulation_config.get("min_soc", 0.10)
    max_soc = simulation_config.get("max_soc", 0.90)

    # Calculate available capacity from current SOC
    available_capacity = nominal_capacity * (initial_soc - min_soc)
    usable_capacity = nominal_capacity * (max_soc - min_soc)

    # Cycles possible
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

        range_analysis.update({
            "avg_speed_kmh": avg_speed_kmh,
            "energy_per_km_Wh": energy_net / cycle_distance_km,
            "capacity_per_km_Ah": capacity_used / cycle_distance_km,
            "range_km": range_km,
            "range_miles": range_km * 0.621371,
            "full_charge_range_km": full_range_km,
            "full_charge_range_miles": full_range_km * 0.621371,
        })

    # Time-based metrics
    drive_time_s = cycles_possible * cycle_duration_s
    full_charge_time_s = full_charge_cycles * cycle_duration_s

    time_label = "flight" if is_aerial else "drive"
    range_analysis.update({
        f"{time_label}_time_min": drive_time_s / 60,
        f"{time_label}_time_hr": drive_time_s / 3600,
        f"full_charge_{time_label}_time_min": full_charge_time_s / 60,
        f"full_charge_{time_label}_time_hr": full_charge_time_s / 3600,
    })

    # Add pack configuration if provided
    if pack_config is not None:
        cells_series = pack_config.get("cells_in_series", 1)
        cells_parallel = pack_config.get("cells_in_parallel", 1)
        total_cells = cells_series * cells_parallel

        range_analysis["pack_config"] = {
            "cells_in_series": cells_series,
            "cells_in_parallel": cells_parallel,
            "total_cells": total_cells,
            "pack_capacity_Ah": nominal_capacity * cells_parallel,
            "pack_energy_Wh": nominal_energy * total_cells,
            "pack_voltage_nominal_V": (
                (cell_design["upper_voltage_cutoff"]["value"] +
                 cell_design["lower_voltage_cutoff"]["value"]) / 2 * cells_series
            ),
        }

        # Scale range for full pack
        range_analysis["pack_range_km"] = range_analysis.get("range_km", 0) * cells_parallel
        range_analysis["pack_full_charge_range_km"] = range_analysis.get("full_charge_range_km", 0) * cells_parallel

    # Add vehicle physics analysis if calculated
    if speed_metadata is not None:
        range_analysis["vehicle_physics"] = {
            "estimated_from_power": True,
            "vehicle_type": speed_metadata["vehicle_type"],
            "avg_speed_kmh": speed_metadata["avg_speed_kmh"],
            "max_speed_kmh": speed_metadata["max_speed_kmh"],
            "weight_kg": vehicle_params.get("weight_kg"),
            "drag_coefficient": vehicle_params.get("drag_coefficient"),
            "frontal_area_m2": vehicle_params.get("frontal_area_m2"),
            "drivetrain_efficiency": vehicle_params.get("drivetrain_efficiency", 0.85),
        }

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
        "config": simulation_config,
    }


def print_drive_cycle_report(result: dict) -> None:
    """
    Print a formatted report of drive cycle simulation results.

    Args:
        result: Result dictionary from run_drive_cycle()
    """
    if not result.get("success"):
        print(f"Simulation failed: {result.get('error', 'Unknown error')}")
        return

    summary = result["summary"]
    energy = result["energy_analysis"]
    range_info = result["range_analysis"]

    print("=" * 70)
    print("DRIVE CYCLE SIMULATION REPORT")
    print("=" * 70)

    print(f"\n{'─' * 70}")
    print("SIMULATION SUMMARY")
    print(f"{'─' * 70}")
    print(f"  Duration:        {summary['duration_s']:.1f} s ({summary['duration_min']:.1f} min)")
    print(f"  Data points:     {summary['data_points']}")
    print(f"  Voltage:         {summary['voltage_min_V']:.3f} - {summary['voltage_max_V']:.3f} V")
    print(f"  Current:         {summary['current_min_A']:.1f} - {summary['current_max_A']:.1f} A")
    print(f"  Power:           {summary['power_min_W']:.1f} - {summary['power_max_W']:.1f} W")
    print(f"  Temperature:     {summary['temperature_min_C']:.1f} - {summary['temperature_max_C']:.1f} °C")
    print(f"  Temp rise:       {summary['temperature_rise_C']:.1f} °C")

    print(f"\n{'─' * 70}")
    print("ENERGY ANALYSIS")
    print(f"{'─' * 70}")
    print(f"  Energy discharged:   {energy['energy_discharged_Wh']:.2f} Wh")
    print(f"  Energy regenerated:  {energy['energy_regenerated_Wh']:.2f} Wh")
    print(f"  Net energy:          {energy['energy_net_Wh']:.2f} Wh")
    print(f"  Capacity used:       {energy['capacity_used_Ah']:.2f} Ah")
    print(f"  SOC change:          {energy['soc_change_pct']:.1f}%")
    if energy['regeneration_ratio_pct'] > 0:
        print(f"  Regen ratio:         {energy['regeneration_ratio_pct']:.1f}%")

    print(f"\n{'─' * 70}")
    print("RANGE ANALYSIS")
    print(f"{'─' * 70}")
    print(f"  Drive cycle:         {range_info['cycle_label']}")
    print(f"  Cycle duration:      {range_info['cycle_duration_s']:.0f} s")

    if range_info.get('cycle_distance_km'):
        print(f"  Cycle distance:      {range_info['cycle_distance_km']:.2f} km")
        print(f"  Average speed:       {range_info.get('avg_speed_kmh', 0):.1f} km/h")
        print(f"  Energy consumption:  {range_info.get('energy_per_km_Wh', 0):.2f} Wh/km")

    print(f"\n  Initial SOC:         {range_info['initial_soc']*100:.0f}%")
    print(f"  SOC limits:          {range_info['min_soc']*100:.0f}% - {range_info['max_soc']*100:.0f}%")
    print(f"  Available capacity:  {range_info['available_capacity_Ah']:.1f} Ah")
    print(f"  Cycles possible:     {range_info['cycles_possible']:.2f}")

    time_label = "Flight" if range_info['is_aerial'] else "Drive"

    if range_info.get('range_km'):
        print(f"\n  Estimated range:     {range_info['range_km']:.1f} km ({range_info['range_miles']:.1f} miles)")

    time_key = "flight_time_min" if range_info['is_aerial'] else "drive_time_min"
    if time_key in range_info:
        print(f"  {time_label} time:        {range_info[time_key]:.1f} min")

    print(f"\n  --- Full Charge ({range_info['max_soc']*100:.0f}% to {range_info['min_soc']*100:.0f}%) ---")
    if range_info.get('full_charge_range_km'):
        print(f"  Range:               {range_info['full_charge_range_km']:.1f} km ({range_info['full_charge_range_miles']:.1f} miles)")

    full_time_key = f"full_charge_{time_label.lower()}_time_min"
    if full_time_key in range_info:
        print(f"  {time_label} time:        {range_info[full_time_key]:.1f} min")

    # Pack configuration
    if "pack_config" in range_info:
        pack = range_info["pack_config"]
        print(f"\n{'─' * 70}")
        print("PACK CONFIGURATION")
        print(f"{'─' * 70}")
        print(f"  Configuration:       {pack['cells_in_series']}S{pack['cells_in_parallel']}P ({pack['total_cells']} cells)")
        print(f"  Pack capacity:       {pack['pack_capacity_Ah']:.1f} Ah")
        print(f"  Pack energy:         {pack['pack_energy_Wh']:.1f} Wh ({pack['pack_energy_Wh']/1000:.2f} kWh)")
        print(f"  Pack voltage (nom):  {pack['pack_voltage_nominal_V']:.1f} V")
        if range_info.get('pack_full_charge_range_km'):
            print(f"  Pack range:          {range_info['pack_full_charge_range_km']:.1f} km")

    # Vehicle physics
    if "vehicle_physics" in range_info:
        vp = range_info["vehicle_physics"]
        print(f"\n{'─' * 70}")
        print("VEHICLE PHYSICS")
        print(f"{'─' * 70}")
        print(f"  Vehicle type:        {vp['vehicle_type']}")
        print(f"  Weight:              {vp['weight_kg']:.1f} kg")
        print(f"  Drag coefficient:    {vp['drag_coefficient']}")
        print(f"  Frontal area:        {vp['frontal_area_m2']:.3f} m²")
        print(f"  Drivetrain eff:      {vp['drivetrain_efficiency']*100:.0f}%")
        print(f"  Avg speed:           {vp['avg_speed_kmh']:.1f} km/h")
        print(f"  Max speed:           {vp['max_speed_kmh']:.1f} km/h")

    print("=" * 70)
