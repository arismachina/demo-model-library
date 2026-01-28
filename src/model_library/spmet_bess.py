"""
SPMeT BESS Duty Cycle Simulation Module (Standalone)

Runs BESS (Battery Energy Storage System) duty cycle simulations with comprehensive
energy and thermal analysis. This module is self-contained and does not depend on spmet.py.

Supports duty cycle types: Peak Shaving, Capacity Firming, Energy Firming, Frequency Regulation
"""

import pybamm
import numpy as np


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

    if "LFP" in cathode_material:
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
        "Positive electrode specific heat capacity [J.kg-1.K-1]": 700,
    }

    positive_cc_params = {
        "Positive current collector thickness [m]": (
            pos_electrode["foil"]["thickness"]["value"] / 1e6
        ),
        "Positive current collector conductivity [S.m-1]": pos_electrode["foil"][
            "material"
        ]["electrical_conductivity"]["value"],
        "Positive current collector density [kg.m-3]": (
            pos_electrode["foil"]["material"]["density"]["value"] * 1000
        ),
        "Positive current collector specific heat capacity [J.kg-1.K-1]": 897,
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
        "Negative electrode specific heat capacity [J.kg-1.K-1]": 700,
    }

    negative_cc_params = {
        "Negative current collector thickness [m]": (
            neg_electrode["foil"]["thickness"]["value"] / 1e6
        ),
        "Negative current collector conductivity [S.m-1]": neg_electrode["foil"][
            "material"
        ]["electrical_conductivity"]["value"],
        "Negative current collector density [kg.m-3]": (
            neg_electrode["foil"]["material"]["density"]["value"] * 1000
        ),
        "Negative current collector specific heat capacity [J.kg-1.K-1]": 385,
    }

    # Separator parameters
    separator = cell_design["separator"]
    separator_params = {
        "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
        "Separator porosity": separator["porosity"]["value"],
        "Separator density [kg.m-3]": (
            separator["material"]["physical_properties"]["density"]["value"] * 1000
        ),
        "Separator specific heat capacity [J.kg-1.K-1]": 700,
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

    # Model options
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    # Capacity calibration
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

    print(f"Convergence tolerance: {TOLERANCE*100:.3f}%")
    print("-" * 80)

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
            print(f"Capacity calibration failed: {e}")
            raise

        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            print(f"Warning: Insufficient cycles: {len(sol_capacity.cycles)}")
            break

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah
        error_percent = abs(1 - scale_factor) * 100

        print(
            f"Iteration {iteration+1:2d}: Capacity = {discharge_capacity:6.2f} Ah, "
            f"Error = {error_percent:6.3f}%"
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

    return default_params, model_options


def _run_pybamm_duty_cycle(
    duty_cycle: dict,
    simulation_config: dict,
    default_params: pybamm.ParameterValues,
    model_options: dict,
) -> dict:
    """
    Execute PyBaMM simulation for BESS duty cycle.

    Returns:
        Dict with simulation results or error
    """
    print("\n" + "=" * 80)
    print("RUNNING DUTY CYCLE")
    print("=" * 80)

    time_s = np.array(duty_cycle["time_s"])
    label = duty_cycle.get("label", "duty_cycle")

    # Get power values (BESS convention: positive = discharge, negative = charge)
    values = np.array(duty_cycle["power_W"])
    print(f"  Type: Power")
    print(f"  Power range: {values.min():.1f} to {values.max():.1f} W")

    drive_data = np.column_stack((time_s, values))

    # Get custom termination thresholds from config
    anode_threshold = simulation_config.get("anode_potential_threshold_V")
    temp_threshold = simulation_config.get("temperature_threshold_K")
    lower_voltage = simulation_config["lower_voltage_cutoff"]
    upper_voltage = simulation_config["upper_voltage_cutoff"]

    # Define cutoff functions for custom terminations
    def anode_potential_cutoff(variables):
        return variables["Anode potential [V]"] - anode_threshold

    def temperature_cutoff(variables):
        return temp_threshold - variables["Volume-averaged cell temperature [K]"]

    # Build termination conditions list
    termination_conditions = []

    if anode_threshold is not None:
        termination_conditions.append(
            pybamm.step.CustomTermination(
                "Anode potential cut-off [V]", anode_potential_cutoff
            )
        )

    if temp_threshold is not None:
        termination_conditions.append(
            pybamm.step.CustomTermination("Temperature cut-off [K]", temperature_cutoff)
        )

    # Always add voltage cutoffs as custom terminations
    def voltage_lower_cutoff(variables):
        return variables["Terminal voltage [V]"] - lower_voltage

    termination_conditions.append(
        pybamm.step.CustomTermination("Lower voltage cut-off [V]", voltage_lower_cutoff)
    )

    def voltage_upper_cutoff(variables):
        return upper_voltage - variables["Terminal voltage [V]"]

    termination_conditions.append(
        pybamm.step.CustomTermination("Upper voltage cut-off [V]", voltage_upper_cutoff)
    )

    print(f"  Label: {label}")
    print(f"  Duration: {time_s[-1]:.1f} s ({time_s[-1]/60:.1f} min)")
    print(f"  Data points: {len(time_s)}")
    print(f"  Custom terminations: {len(termination_conditions)}")

    # Build experiment with custom terminations
    duty_cycle_step = pybamm.step.power(
        drive_data,
        duration=time_s[-1],
        termination=termination_conditions,
    )

    period = simulation_config.get("period", "10 second")
    experiment = pybamm.Experiment([duty_cycle_step], period=period)

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
        ],
    )

    sim = pybamm.Simulation(
        model,
        parameter_values=default_params,
        experiment=experiment,
        var_pts=var_pts,
    )

    initial_soc = simulation_config.get("initial_soc", 0.5)

    try:
        print(f"  Running simulation (initial SOC: {initial_soc*100:.0f}%)...")
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        soc = (
            initial_soc
            - solution["Discharge capacity [A.h]"].entries
            / default_params["Nominal cell capacity [A.h]"]
        )
        termination_reason = getattr(solution, "termination", "completed")

        result = {
            "time_s": solution["Time [s]"].entries,
            "voltage_V": solution["Terminal voltage [V]"].entries,
            "current_A": solution["Current [A]"].entries,
            "temperature_K": solution["Volume-averaged cell temperature [K]"].entries,
            "capacity_Ah": solution["Discharge capacity [A.h]"].entries,
            "energy_Wh": solution["Discharge energy [W.h]"].entries,
            "power_W": solution["Terminal power [W]"].entries,
            "soc": soc,
            "anode_potential_V": solution["Anode potential [V]"].entries,
            "experiment_label": label,
            "termination_reason": termination_reason,
            "success": True,
        }

        print(f"  Completed: {len(result['time_s'])} data points")
        if termination_reason != "completed" and termination_reason != "final time":
            print(f"  Termination: {termination_reason}")
        return result

    except pybamm.SolverError as e:
        print(f"  Failed: {str(e)[:100]}")
        return {
            "experiment_label": label,
            "success": False,
            "error": str(e),
        }


def run_duty_cycle(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run a BESS duty cycle simulation with comprehensive analysis.

    This is a standalone function that handles:
    1. PyBaMM parameter setup from cell design
    2. Capacity calibration
    3. Duty cycle simulation
    4. Energy and thermal analysis

    Args:
        cell_design: Cell design parameters dictionary (from manifest) containing:
            - nominal_capacity: {"value": float} - Nominal capacity [Ah]
            - nominal_voltage: {"value": float} - Nominal voltage [V]
            - nominal_energy: {"value": float} - Nominal energy [Wh] (optional)
            - upper_voltage_cutoff: {"value": float} - Upper voltage limit [V]
            - lower_voltage_cutoff: {"value": float} - Lower voltage limit [V]
            - cell_volume: {"value": float} - Cell volume [L]
            - positive_electrode: Dict with electrode parameters
            - negative_electrode: Dict with electrode parameters
            - separator: Dict with separator parameters
            - jelly_roll: {"count": {"value": int}} - Number of jelly rolls

        simulation_config: Simulation configuration containing:
            - pack_energy_kWh: Pack total energy capacity [kWh]
            - pack_voltage_V: Pack nominal voltage [V]
            - rated_power_kW: Pack rated power demand [kW] (scales per-unit power)
            - ambient_temperature: Ambient temperature [K]
            - initial_temperature: Initial cell temperature [K]
            - initial_soc: Initial state of charge [0-1]
            - contact_resistance: Contact resistance [Ohm]
            - total_heat_transfer_coefficient: Heat transfer coeff [W/m2K]
            - cooling_surface_area: Cooling surface area [m2]
            - period: Sampling period string (default: "10 second")
            - duty_cycle: Dict with duty cycle data:
                - time_s: Array of time points [s]
                - power_pu: Array of per-unit power values [-1 to 1], normalized by abs max
                            (positive = discharge, negative = charge)
                            Scaled by peak_power_demand_kW to get actual pack power
                - label: Label for the duty cycle
            - min_soc: Minimum SOC for cycling (default: 0.10)
            - max_soc: Maximum SOC for cycling (default: 0.90)
            - anode_potential_threshold_V: (optional) Terminate if anode potential drops below this [V]
            - temperature_threshold_K: (optional) Terminate if temperature exceeds this [K]

            Note: Pack configuration (cells_series, cells_parallel) is calculated internally
            from pack_energy_kWh, pack_voltage_V, and cell properties.

    Returns:
        Dictionary containing:
            - success: Boolean indicating simulation success
            - error: Error message if failed
            - timeseries: Dict with time series arrays
            - summary: Dict with simulation summary
            - energy_analysis: Dict with energy metrics
            - cycle_analysis: Dict with cycling metrics
            - termination_reason: Why the simulation ended
            - config: Original simulation config
    """
    # Validate inputs
    if "duty_cycle" not in simulation_config:
        raise ValueError("simulation_config must contain 'duty_cycle'")

    duty_cycle = simulation_config["duty_cycle"]
    if "time_s" not in duty_cycle:
        raise ValueError("duty_cycle must contain 'time_s'")

    # Get pack parameters
    pack_energy_kWh = simulation_config["pack_energy_kWh"]
    pack_voltage_V = simulation_config["pack_voltage_nom_V"]
    rated_power_kW = simulation_config["peak_power_demand_kW"]

    # Get cell parameters for pack configuration calculation
    cell_nominal_voltage = cell_design["nominal_voltage"]["value"]
    cell_nominal_energy_Wh = cell_design.get("nominal_energy", {}).get("value")
    if cell_nominal_energy_Wh is None:
        cell_nominal_energy_Wh = (
            cell_design["nominal_capacity"]["value"] * cell_nominal_voltage
        )

    # Calculate pack configuration from pack and cell properties
    cells_series = int(round(pack_voltage_V / cell_nominal_voltage))
    cells_parallel = int(
        round((pack_energy_kWh * 1000) / (cell_nominal_energy_Wh * cells_series))
    )
    total_cells = cells_series * cells_parallel

    # Convert per-unit power to pack power, then to cell power
    time_s = np.array(duty_cycle["time_s"])
    power_pu = np.array(duty_cycle["power_pu"])  # Per-unit power (normalized by abs max)
    pack_power_W = power_pu * rated_power_kW * 1000  # Scale by rated peak power
    cell_power_W = pack_power_W / total_cells

    print(f"\n  Pack config: {cells_series}S{cells_parallel}P ({total_cells} cells)")
    print(f"  Pack energy: {pack_energy_kWh:.2f} kWh")
    print(f"  Pack voltage: {pack_voltage_V:.1f} V")
    print(f"  Rated peak power: {rated_power_kW:.1f} kW")
    print(
        f"  Pack power range: {pack_power_W.min()/1000:.1f} to {pack_power_W.max()/1000:.1f} kW"
    )
    print(f"  Cell power range: {cell_power_W.min():.1f} to {cell_power_W.max():.1f} W")
    print(f"  Cell nominal voltage: {cell_nominal_voltage:.1f} V")
    print(f"  Cell nominal capacity: {cell_design['nominal_capacity']['value']:.2f} Ah")
    print(f"  Cell nominal energy: {cell_nominal_energy_Wh:.1f} Wh")

    # Update duty_cycle with cell-level power
    duty_cycle = {**duty_cycle, "power_W": cell_power_W}

    # Build pack_config for reporting
    pack_config = {
        "cells_in_series": cells_series,
        "cells_in_parallel": cells_parallel,
        "pack_energy_kWh": pack_energy_kWh,
        "pack_voltage_V": pack_voltage_V,
        "rated_power_kW": rated_power_kW,
    }

    # Get cell parameters
    nominal_capacity = cell_design["nominal_capacity"]["value"]
    nominal_energy = cell_design.get("nominal_energy", {}).get("value")
    if nominal_energy is None:
        avg_voltage = (
            cell_design["upper_voltage_cutoff"]["value"]
            + cell_design["lower_voltage_cutoff"]["value"]
        ) / 2
        nominal_energy = nominal_capacity * avg_voltage

    # Build PyBaMM parameters and run capacity calibration
    default_params, model_options = _build_pybamm_params(cell_design, simulation_config)

    # Run simulation
    sim_result = _run_pybamm_duty_cycle(
        duty_cycle=duty_cycle,
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
        "time_s": sim_result["time_s"].tolist(),
        "voltage_V": sim_result["voltage_V"].tolist(),
        "current_A": sim_result["current_A"].tolist(),
        "power_W": sim_result["power_W"].tolist(),
        "temperature_K": sim_result["temperature_K"].tolist(),
        "temperature_C": (sim_result["temperature_K"] - 273.15).tolist(),
        "capacity_Ah": sim_result["capacity_Ah"].tolist(),
        "soc": sim_result["soc"].tolist(),
        "energy_Wh": sim_result["energy_Wh"].tolist(),
        "anode_potential_V": sim_result["anode_potential_V"].tolist(),
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
    sim_soc = sim_result["soc"]

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
        "soc_min": float(sim_soc.min()),
        "soc_max": float(sim_soc.max()),
        "final_soc": float(sim_soc[-1]),
        "data_points": len(sim_time),
    }

    # Energy analysis
    dt = np.diff(sim_time)
    power_mid = (sim_power[:-1] + sim_power[1:]) / 2

    discharge_mask = power_mid > 0
    charge_mask = power_mid < 0

    energy_discharged = float(
        np.sum(power_mid[discharge_mask] * dt[discharge_mask]) / 3600
    )
    energy_charged = float(-np.sum(power_mid[charge_mask] * dt[charge_mask]) / 3600)
    energy_net = energy_discharged - energy_charged

    capacity_discharged = (
        float(sim_capacity[-1] - sim_capacity[0])
        if sim_capacity[-1] > sim_capacity[0]
        else 0
    )
    capacity_charged = (
        float(sim_capacity[0] - sim_capacity[-1])
        if sim_capacity[-1] < sim_capacity[0]
        else 0
    )

    initial_soc = simulation_config.get("initial_soc", 0.5)
    soc_change = (sim_soc[-1] - initial_soc) * 100

    energy_analysis = {
        "energy_discharged_Wh": energy_discharged,
        "energy_charged_Wh": energy_charged,
        "energy_net_Wh": energy_net,
        "capacity_discharged_Ah": capacity_discharged,
        "capacity_charged_Ah": capacity_charged,
        "soc_change_pct": soc_change,
        "round_trip_efficiency_pct": (
            energy_discharged / energy_charged * 100 if energy_charged > 0 else 0
        ),
    }

    # Cycle analysis (BESS-specific)
    cycle_duration_s = summary["duration_s"]
    label = duty_cycle.get("label", "duty_cycle")

    # SOC limits for cycling
    min_soc = simulation_config.get("min_soc", 0.10)
    max_soc = simulation_config.get("max_soc", 0.90)

    usable_capacity = nominal_capacity * (max_soc - min_soc)
    usable_energy = nominal_energy * (max_soc - min_soc)

    # Calculate throughput per cycle
    throughput_Ah = abs(capacity_discharged) + abs(capacity_charged)
    throughput_Wh = energy_discharged + energy_charged

    cycle_analysis = {
        "cycle_label": label,
        "cycle_duration_s": cycle_duration_s,
        "cycle_duration_min": cycle_duration_s / 60,
        "cycle_duration_hr": cycle_duration_s / 3600,
        "initial_soc": initial_soc,
        "final_soc": float(sim_soc[-1]),
        "min_soc_limit": min_soc,
        "max_soc_limit": max_soc,
        "usable_capacity_Ah": usable_capacity,
        "usable_energy_Wh": usable_energy,
        "throughput_Ah": throughput_Ah,
        "throughput_Wh": throughput_Wh,
        "cycles_per_day": 86400 / cycle_duration_s if cycle_duration_s > 0 else 0,
        "daily_throughput_Ah": (
            throughput_Ah * 86400 / cycle_duration_s if cycle_duration_s > 0 else 0
        ),
        "daily_throughput_Wh": (
            throughput_Wh * 86400 / cycle_duration_s if cycle_duration_s > 0 else 0
        ),
    }

    # Add pack configuration if provided
    if pack_config is not None:
        cells_series = pack_config.get("cells_in_series", 1)
        cells_parallel = pack_config.get("cells_in_parallel", 1)
        total_cells = cells_series * cells_parallel

        pack_info = {
            "cells_in_series": cells_series,
            "cells_in_parallel": cells_parallel,
            "total_cells": total_cells,
            "pack_capacity_Ah": nominal_capacity * cells_parallel,
            "pack_energy_Wh": nominal_energy * total_cells,
            "pack_voltage_nominal_V": (
                (
                    cell_design["upper_voltage_cutoff"]["value"]
                    + cell_design["lower_voltage_cutoff"]["value"]
                )
                / 2
                * cells_series
            ),
            "pack_usable_capacity_Ah": usable_capacity * cells_parallel,
            "pack_usable_energy_Wh": usable_energy * total_cells,
            "pack_throughput_Ah": throughput_Ah * cells_parallel,
            "pack_throughput_Wh": throughput_Wh * total_cells,
            "pack_daily_throughput_kWh": (
                throughput_Wh * total_cells * 86400 / cycle_duration_s / 1000
                if cycle_duration_s > 0
                else 0
            ),
        }
        cycle_analysis["pack_config"] = pack_info

    return {
        "success": True,
        "timeseries": timeseries,
        "summary": summary,
        "energy_analysis": energy_analysis,
        "cycle_analysis": cycle_analysis,
        "termination_reason": termination_reason,
        "config": simulation_config,
    }


def print_duty_cycle_report(result: dict) -> None:
    """
    Print a formatted report of BESS duty cycle simulation results.

    Args:
        result: Result dictionary from run_duty_cycle()
    """
    if not result.get("success"):
        print(f"Simulation failed: {result.get('error', 'Unknown error')}")
        return

    summary = result["summary"]
    energy = result["energy_analysis"]
    cycle_info = result["cycle_analysis"]

    print("=" * 70)
    print("BESS DUTY CYCLE SIMULATION REPORT")
    print("=" * 70)

    print(f"\n{'─' * 70}")
    print("SIMULATION SUMMARY")
    print(f"{'─' * 70}")
    print(
        f"  Duration:        {summary['duration_s']:.1f} s ({summary['duration_min']:.1f} min)"
    )
    print(f"  Data points:     {summary['data_points']}")
    print(
        f"  Voltage:         {summary['voltage_min_V']:.3f} - {summary['voltage_max_V']:.3f} V"
    )
    print(
        f"  Current:         {summary['current_min_A']:.1f} - {summary['current_max_A']:.1f} A"
    )
    print(
        f"  Power:           {summary['power_min_W']:.1f} - {summary['power_max_W']:.1f} W"
    )
    print(
        f"  Temperature:     {summary['temperature_min_C']:.1f} - {summary['temperature_max_C']:.1f} °C"
    )
    print(f"  Temp rise:       {summary['temperature_rise_C']:.1f} °C")
    print(
        f"  SOC range:       {summary['soc_min']*100:.1f}% - {summary['soc_max']*100:.1f}%"
    )
    print(f"  Final SOC:       {summary['final_soc']*100:.1f}%")

    print(f"\n{'─' * 70}")
    print("ENERGY ANALYSIS")
    print(f"{'─' * 70}")
    print(f"  Energy discharged:   {energy['energy_discharged_Wh']:.2f} Wh")
    print(f"  Energy charged:      {energy['energy_charged_Wh']:.2f} Wh")
    print(f"  Net energy:          {energy['energy_net_Wh']:.2f} Wh")
    print(f"  Capacity discharged: {energy['capacity_discharged_Ah']:.3f} Ah")
    print(f"  Capacity charged:    {energy['capacity_charged_Ah']:.3f} Ah")
    print(f"  SOC change:          {energy['soc_change_pct']:+.1f}%")
    if energy["round_trip_efficiency_pct"] > 0:
        print(f"  Round-trip eff:      {energy['round_trip_efficiency_pct']:.1f}%")

    print(f"\n{'─' * 70}")
    print("CYCLE ANALYSIS")
    print(f"{'─' * 70}")
    print(f"  Duty cycle:          {cycle_info['cycle_label']}")
    print(
        f"  Cycle duration:      {cycle_info['cycle_duration_s']:.0f} s ({cycle_info['cycle_duration_min']:.1f} min)"
    )
    print(
        f"  SOC limits:          {cycle_info['min_soc_limit']*100:.0f}% - {cycle_info['max_soc_limit']*100:.0f}%"
    )
    print(f"  Usable capacity:     {cycle_info['usable_capacity_Ah']:.1f} Ah")
    print(f"  Usable energy:       {cycle_info['usable_energy_Wh']:.1f} Wh")
    print(
        f"  Throughput/cycle:    {cycle_info['throughput_Ah']:.3f} Ah / {cycle_info['throughput_Wh']:.2f} Wh"
    )
    print(f"  Cycles per day:      {cycle_info['cycles_per_day']:.1f}")
    print(
        f"  Daily throughput:    {cycle_info['daily_throughput_Ah']:.1f} Ah / {cycle_info['daily_throughput_Wh']:.1f} Wh"
    )

    # Pack configuration
    if "pack_config" in cycle_info:
        pack = cycle_info["pack_config"]
        print(f"\n{'─' * 70}")
        print("PACK CONFIGURATION")
        print(f"{'─' * 70}")
        print(
            f"  Configuration:       {pack['cells_in_series']}S{pack['cells_in_parallel']}P ({pack['total_cells']} cells)"
        )
        print(f"  Pack capacity:       {pack['pack_capacity_Ah']:.1f} Ah")
        print(
            f"  Pack energy:         {pack['pack_energy_Wh']:.1f} Wh ({pack['pack_energy_Wh']/1000:.2f} kWh)"
        )
        print(f"  Pack voltage (nom):  {pack['pack_voltage_nominal_V']:.1f} V")
        print(f"  Pack usable cap:     {pack['pack_usable_capacity_Ah']:.1f} Ah")
        print(
            f"  Pack usable energy:  {pack['pack_usable_energy_Wh']:.1f} Wh ({pack['pack_usable_energy_Wh']/1000:.2f} kWh)"
        )
        print(
            f"  Pack throughput:     {pack['pack_throughput_Ah']:.1f} Ah / {pack['pack_throughput_Wh']:.1f} Wh"
        )
        print(f"  Daily throughput:    {pack['pack_daily_throughput_kWh']:.2f} kWh")

    # Termination reason
    termination = result.get("termination_reason", "completed")
    if termination != "completed" and termination != "final time":
        print(f"\n{'─' * 70}")
        print(f"  TERMINATION: {termination}")

    print("=" * 70)
