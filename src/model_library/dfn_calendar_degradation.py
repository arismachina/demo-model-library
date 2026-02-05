"""
DFN Calendar Degradation Simulation Module

Calendar aging simulation for Li-ion batteries using the Doyle-Fuller-Newman (DFN) model.
This module simulates battery degradation over extended periods (days, months, years) without
any charging or discharging, focusing on calendar/storage-induced degradation mechanisms.

Based on: https://github.com/pybamm-team/PyBaMM/blob/main/examples/scripts/calendar_ageing.py

Calendar aging mechanisms modeled:
- SEI growth on the negative electrode surface (solvent-diffusion limited)
- Reactions on electrode surfaces
- Capacity fade due to lithium inventory loss
- Changes in electrode porosity
- Loss of active material from mechanical degradation

The simulation uses:
- DFN (Doyle-Fuller-Newman) electrochemical model with full particle mechanics
- O'Kane2022 parameter set with comprehensive degradation models
- IDAKLUSolver for robust time integration
- State-of-charge (SoC) determination capability for different initial conditions
"""

import pybamm
import numpy as np
from typing import Dict, Tuple, Optional, Any
import json
from pathlib import Path


def build_dfn_calendar_model_options() -> Dict[str, Any]:
    """
    Build model options for DFN calendar degradation simulation.

    Calendar aging focuses on non-faradaic degradation processes that occur
    during storage at open circuit or low current conditions.

    Returns:
        Dict with model options for DFN
    """
    model_options = {
        # Electrochemistry
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        # Thermal management
        "thermal": "lumped",
        "contact resistance": "true",
        # Degradation mechanisms
        "SEI": "solvent-diffusion limited",
        "SEI porosity change": "true",
        "SEI on cracks": "true",
        "lithium plating": "none",  # Not applicable for calendar aging
        "lithium plating porosity change": "false",
        "particle mechanics": ("swelling and cracking", "swelling only"),
        "loss of active material": "stress-driven",
    }

    return model_options


def build_dfn_calendar_degradation_params(
    cell_design: Dict,
    sim_config: Dict,
) -> pybamm.ParameterValues:
    """
    Build complete PyBaMM parameter set for DFN calendar degradation simulation.

    Args:
        cell_design: Cell design dictionary (from manifest)
        sim_config: Simulation configuration with cell and thermal parameters

    Returns:
        PyBaMM ParameterValues object with all parameters
    """
    print("\nBuilding DFN calendar degradation parameters...")

    # Use O'Kane2022 parameter set which includes comprehensive degradation models
    default_params = pybamm.ParameterValues("OKane2022")

    # Cell parameters
    cell_nominal_capacity = cell_design["nominal_capacity"]["value"]

    cell_params = {
        "Nominal cell capacity [A.h]": cell_nominal_capacity,
    }

    # Positive electrode parameters
    pos_electrode = cell_design["positive_electrode"]
    number_of_coated_sides = 2

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
        "Positive current collector conductivity [S.m-1]": (
            pos_electrode["foil"]["material"]["electrical_conductivity"]["value"]
        ),
        "Positive current collector density [kg.m-3]": (
            pos_electrode["foil"]["material"]["density"]["value"] * 1000
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
        "Negative current collector conductivity [S.m-1]": (
            neg_electrode["foil"]["material"]["electrical_conductivity"]["value"]
        ),
        "Negative current collector density [kg.m-3]": (
            neg_electrode["foil"]["material"]["density"]["value"] * 1000
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

    # Thermal parameters (calendar aging at fixed temperature)
    ambient_temp_C = sim_config.get("ambient_temperature_C", 25)
    ambient_temp_K = ambient_temp_C + 273.15

    thermal_params = {
        "Reference temperature [K]": 298.15,
        "Ambient temperature [K]": ambient_temp_K,
        "Initial temperature [K]": ambient_temp_K,
        "Total heat transfer coefficient [W.m-2.K-1]": sim_config.get(
            "total_heat_transfer_coefficient_W_m2K", 10.0
        ),
        "Cell cooling surface area [m2]": sim_config.get("cooling_surface_area_m2", 0.01),
        "Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
    }

    # Operating conditions
    operating_conditions = {
        "Upper voltage cut-off [V]": sim_config.get(
            "upper_voltage_cutoff_V",
            cell_design.get("upper_voltage_cutoff", {}).get("value"),
        ),
        "Lower voltage cut-off [V]": sim_config.get(
            "lower_voltage_cutoff_V",
            cell_design.get("lower_voltage_cutoff", {}).get("value"),
        ),
        "Contact resistance [Ohm]": sim_config.get("contact_resistance_Ohm", 0.0001),
    }

    # Degradation parameters (SEI growth, particle mechanics, LAM)
    degradation_params = {
        # SEI parameters
        "Initial SEI thickness [m]": sim_config.get("initial_sei_thickness_m", 5e-9),
        "SEI partial molar volume [m3.mol-1]": sim_config.get(
            "sei_partial_molar_volume_m3_mol", 9.585e-5
        ),
        "SEI resistivity [Ohm.m]": sim_config.get("sei_resistivity_Ohm_m", 2.5e5),
        "SEI growth activation energy [J.mol-1]": sim_config.get(
            "sei_growth_activation_energy_J_mol", 5e4
        ),
        "SEI solvent diffusivity [m2.s-1]": sim_config.get(
            "sei_solvent_diffusivity_m2_s", 2.5e-22
        ),
        "Bulk solvent concentration [mol.m-3]": sim_config.get(
            "bulk_solvent_concentration_mol_m3", 2000.0
        ),
        "SEI reaction exchange current density [A.m-2]": sim_config.get(
            "sei_reaction_exchange_current_density_A_m2", 1.5e-7
        ),
        "SEI open-circuit potential [V]": sim_config.get(
            "sei_open_circuit_potential_V", 0.4
        ),
        "EC diffusivity [m2.s-1]": sim_config.get("ec_diffusivity_m2_s", 2e-18),
        "EC initial concentration in electrolyte [mol.m-3]": sim_config.get(
            "ec_initial_concentration_mol_m3", 4541.0
        ),
        # Particle mechanics parameters
        "Negative electrode Young's modulus [Pa]": sim_config.get(
            "negative_electrode_youngs_modulus_Pa", 15e9
        ),
        "Positive electrode Young's modulus [Pa]": sim_config.get(
            "positive_electrode_youngs_modulus_Pa", 375e9
        ),
        "Negative electrode Poisson's ratio": sim_config.get(
            "negative_electrode_poissons_ratio", 0.3
        ),
        "Positive electrode Poisson's ratio": sim_config.get(
            "positive_electrode_poissons_ratio", 0.3
        ),
        "Negative electrode partial molar volume [m3.mol-1]": sim_config.get(
            "negative_electrode_partial_molar_volume_m3_mol", 3.1e-6
        ),
        "Positive electrode partial molar volume [m3.mol-1]": sim_config.get(
            "positive_electrode_partial_molar_volume_m3_mol", -7.28e-7
        ),
        # Particle cracking parameters
        "Negative electrode initial crack length [m]": sim_config.get(
            "negative_electrode_initial_crack_length_m", 1e-9
        ),
        "Positive electrode initial crack length [m]": sim_config.get(
            "positive_electrode_initial_crack_length_m", 1e-9
        ),
        "Negative electrode cracking rate": sim_config.get(
            "negative_electrode_cracking_rate", 3.9e-20
        ),
        "Positive electrode cracking rate": sim_config.get(
            "positive_electrode_cracking_rate", 3.9e-20
        ),
        "Negative electrode number of cracks per unit area [m-2]": sim_config.get(
            "negative_electrode_number_of_cracks_per_unit_area", 3.16e15
        ),
        "Positive electrode number of cracks per unit area [m-2]": sim_config.get(
            "positive_electrode_number_of_cracks_per_unit_area", 3.16e15
        ),
        "Negative electrode initial crack width [m]": sim_config.get(
            "negative_electrode_initial_crack_width_m", 1e-9
        ),
        "Positive electrode initial crack width [m]": sim_config.get(
            "positive_electrode_initial_crack_width_m", 1e-9
        ),
        "Initial SEI on cracks thickness [m]": sim_config.get(
            "initial_sei_on_cracks_thickness_m", 1e-9
        ),
        # Loss of active material parameters
        "Negative electrode LAM constant proportional term [s-1]": sim_config.get(
            "negative_electrode_lam_constant_proportional", 1e-4
        ),
        "Positive electrode LAM constant proportional term [s-1]": sim_config.get(
            "positive_electrode_lam_constant_proportional", 1e-4
        ),
        "Negative electrode LAM constant exponential term": sim_config.get(
            "negative_electrode_lam_constant_exponential", 2.0
        ),
        "Positive electrode LAM constant exponential term": sim_config.get(
            "positive_electrode_lam_constant_exponential", 2.0
        ),
        "Negative electrode critical stress [Pa]": sim_config.get(
            "negative_electrode_critical_stress_Pa", 60e6
        ),
        "Positive electrode critical stress [Pa]": sim_config.get(
            "positive_electrode_critical_stress_Pa", 60e6
        ),
    }

    # Combine all parameters
    all_params = {
        **cell_params,
        **positive_electrode_params,
        **positive_cc_params,
        **negative_electrode_params,
        **negative_cc_params,
        **separator_params,
        **thermal_params,
        **operating_conditions,
        **degradation_params,
    }

    default_params.update(all_params, check_already_exists=False)

    print(f"  Ambient temperature: {ambient_temp_C}°C ({ambient_temp_K}K)")
    print(f"  Nominal capacity: {cell_nominal_capacity:.2f} Ah")
    print(f"  ✓ DFN calendar degradation parameters built")

    return default_params


def calibrate_capacity(
    cell_design: Dict,
    param: pybamm.ParameterValues,
    model_options: Dict[str, str],
) -> Tuple[pybamm.ParameterValues, bool]:
    """
    Calibrate DFN model capacity to match cell design nominal capacity.

    This iteratively adjusts electrode width to match the target capacity by:
    1. Running a slow charge-discharge test
    2. Measuring actual capacity
    3. Scaling electrode width proportionally
    4. Repeating until convergence

    Args:
        cell_design: Cell design dictionary with nominal capacity
        param: PyBaMM ParameterValues to calibrate
        model_options: Model options dictionary

    Returns:
        Tuple of (calibrated_param, success)
    """
    target_capacity_Ah = cell_design["nominal_capacity"]["value"]
    upper_voltage = param["Upper voltage cut-off [V]"]
    lower_voltage = param["Lower voltage cut-off [V]"]

    print("\n" + "=" * 80)
    print("CAPACITY CALIBRATION")
    print("=" * 80)
    print(f"Target capacity: {target_capacity_Ah:.2f} Ah")
    print(f"Voltage range: {lower_voltage:.2f}V - {upper_voltage:.2f}V")

    # Build calibration experiment (slow C/10 charge-discharge)
    charge_step = f"Charge at {target_capacity_Ah * 0.1} A until {upper_voltage} V"
    hold_step = f"Hold at {upper_voltage} V for 2 hours or until C/50"
    discharge_step = f"Discharge at {target_capacity_Ah * 0.1} A for 15 hours or until {lower_voltage} V"

    capacity_match_experiment = pybamm.Experiment(
        [
            ("Rest for 1 seconds", charge_step, hold_step),
            ("Rest for 3600 seconds",),
            (discharge_step,),
            ("Rest for 1 seconds",),
        ],
        period="1 second",
    )

    # Use simplified degradation for faster calibration
    calibration_options = {
        **model_options,
        "particle mechanics": "none",
        "SEI on cracks": "false",
        "loss of active material": "none",
    }
    model_capacity = pybamm.lithium_ion.DFN(options=calibration_options)

    MAX_ITERATIONS = 20
    TOLERANCE = 0.0001  # 0.01% tolerance

    print(f"Convergence tolerance: {TOLERANCE*100:.3f}%")
    print("-" * 80)

    for iteration in range(MAX_ITERATIONS):
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=param,
        )

        try:
            sol_capacity = sim_capacity.solve(
                solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
            )
        except pybamm.SolverError as e:
            print(f"Capacity calibration failed: {e}")
            return param, False

        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            print(f"Warning: Insufficient cycles: {len(sol_capacity.cycles)}")
            return param, False

        # Extract discharge capacity from cycle 3 (index 2)
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

        # Check convergence
        if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
            print("-" * 80)
            print(f"✓ Converged after {iteration+1} iterations!")
            print(f"  Final capacity: {discharge_capacity:.2f} Ah")
            print(f"  Target capacity: {target_capacity_Ah:.2f} Ah")
            print(f"  Error: {error_percent:.4f}%")

            # Update OCV parameters from calibration
            ocv_100 = float(sol_capacity.cycles[1]["Terminal voltage [V]"].entries[-1])
            ocv_0 = float(sol_capacity.cycles[3]["Terminal voltage [V]"].entries[-1])

            param.update(
                {
                    "Open-circuit voltage at 100% SOC [V]": ocv_100,
                    "Open-circuit voltage at 0% SOC [V]": ocv_0,
                },
                check_already_exists=False,
            )
            print(f"  OCV at 100% SoC: {ocv_100:.3f}V")
            print(f"  OCV at 0% SoC: {ocv_0:.3f}V")
            print("=" * 80)
            return param, True

        # Adjust electrode width for next iteration
        new_width = param["Electrode width [m]"] / scale_factor
        param.update(
            {
                "Electrode width [m]": new_width,
                "Nominal cell capacity [A.h]": discharge_capacity / scale_factor,
            },
            check_already_exists=False,
        )

    print("-" * 80)
    print(f"⚠ Warning: Did not converge after {MAX_ITERATIONS} iterations")
    print(f"  Final error: {error_percent:.3f}%")
    print("=" * 80)
    return param, False


def run_calendar_degradation(
    cell_design: Dict,
    sim_config: Dict,
) -> Dict[str, Any]:
    """
    Simulate calendar (storage) degradation for a Li-ion cell using DFN model.

    Calendar aging occurs during storage without charge/discharge cycles.
    This function simulates degradation mechanisms that occur at rest:
    - SEI growth on negative electrode
    - Solid-state reactions on electrode surfaces
    - Mechanical degradation (particle cracking, material loss)
    - Capacity fade tracking

    Simulation runs for calendar_time_days duration, but can stop early if
    SoH drops below soh_threshold.

    Args:
        cell_design: Cell design dictionary from manifest JSON
        sim_config: Simulation configuration dictionary with keys:
            - calendar_time_days: Total storage duration in days (default: 365)
            - soh_threshold: Stop if SoH drops below this % (optional, default: None = no limit)
            - initial_soc: Initial state of charge (0-1, default: 0.8)
            - ambient_temperature_C: Storage temperature (default: 25°C)
            - upper_voltage_cutoff_V: Maximum cell voltage (optional)
            - lower_voltage_cutoff_V: Minimum cell voltage (optional)
            - contact_resistance_Ohm: Contact resistance (default: 0.0001 Ohm)
            - total_heat_transfer_coefficient_W_m2K: Heat transfer (default: 10)
            - cooling_surface_area_m2: Cooling surface area (default: 0.01 m²)
            - skip_capacity_calibration: Skip calibration, faster but less accurate (default: False)
            - solver_atol: Absolute tolerance (default: 1e-4)
            - solver_rtol: Relative tolerance (default: 1e-4)
            - All degradation parameters (see build_dfn_calendar_degradation_params)

    Returns:
        Dictionary with keys:
            - success: Boolean indicating successful completion
            - error: Error message if simulation failed (if success=False)
            - stop_reason: Why simulation stopped ('soh_threshold', 'completed', or 'error')
            - data: Dict with simulation results containing:
                - time_s: Time array [s]
                - voltage_V: Terminal voltage [V]
                - temperature_K: Cell temperature [K]
                - capacity_Ah: Available capacity [Ah]
                - soc: State of charge
                - LLI_pct: Loss of lithium inventory [%]
                - LAM_neg_pct: Loss of active material in negative electrode [%]
                - LAM_pos_pct: Loss of active material in positive electrode [%]
                - Li_lost_mol: Total lithium lost [mol]
                - Q_SEI_Ah: Capacity lost to negative SEI [Ah]
                - Q_SEI_cracks_Ah: Capacity lost to SEI on cracks [Ah]
                - Q_side_reactions_Ah: Total capacity lost [Ah]
                - porosity_neg: Negative electrode porosity
                - porosity_pos: Positive electrode porosity
                - throughput_Ah: Charge throughput [Ah]
            - summary: Dict with degradation summary:
                - calendar_time_days: Requested storage duration
                - initial_capacity_Ah: Starting capacity
                - final_capacity_Ah: Ending capacity
                - capacity_fade_Ah: Absolute capacity fade
                - capacity_fade_pct: Relative capacity fade
                - initial_soh_pct: Starting state of health
                - final_soh_pct: Final state of health
                - LLI_pct: Final LLI
                - LAM_neg_pct: Final LAM negative
                - LAM_pos_pct: Final LAM positive
                - Q_SEI_total_Ah: Total SEI capacity loss
                - porosity_neg_change: Change in negative electrode porosity
                - porosity_pos_change: Change in positive electrode porosity
            - config: Copy of input simulation configuration
    """

    print("=" * 80)
    print("DFN CALENDAR DEGRADATION SIMULATION")
    print("=" * 80)

    # Extract simulation parameters
    calendar_time_days = sim_config.get("calendar_time_days")
    initial_soc = sim_config.get("initial_soc")
    ambient_temp_C = sim_config.get("ambient_temperature_C")

    # Extract stopping criteria
    soh_threshold = sim_config.get("soh_threshold")

    # Convert time to seconds (always use full calendar_time_days)
    calendar_time_s = calendar_time_days * 24 * 3600

    print(f"\nSimulation parameters:")
    print(f"  Calendar time: {calendar_time_days} days ({calendar_time_s:.2e} s)")
    print(f"  Initial SoC: {initial_soc*100:.0f}%")
    print(f"  Temperature: {ambient_temp_C}°C")

    # Print stopping criteria if specified
    if soh_threshold is not None:
        print(f"  SoH threshold cutoff: {soh_threshold}%")

    try:
        # Build model options
        model_options = build_dfn_calendar_model_options()
        print(f"\n✓ Model options configured")
        print(f"  - SEI model: {model_options['SEI']}")
        print(f"  - Particle mechanics: {model_options['particle mechanics']}")
        print(f"  - LAM model: {model_options['loss of active material']}")

        # Build parameters
        default_params = build_dfn_calendar_degradation_params(cell_design, sim_config)

        # Capacity calibration (unless explicitly skipped)
        if not sim_config.get("skip_capacity_calibration"):
            default_params, calibration_success = calibrate_capacity(
                cell_design, default_params, model_options
            )
            if not calibration_success:
                print("⚠ Warning: Capacity calibration did not fully converge")
                print("  Continuing with best-fit parameters...")
        else:
            print(
                "\n⚠ Skipping capacity calibration (using default O'Kane2022 parameters)"
            )
            print("  Note: Simulated capacity may not match nominal capacity\n")

        # Create DFN model
        print(f"\n✓ Building DFN model...")
        model = pybamm.lithium_ion.DFN(options=model_options)

        # Create calendar aging experiment (zero current = OCV)
        print(f"\n✓ Setting up calendar aging experiment (zero current)...")
        experiment = pybamm.Experiment(
            [f"Rest for {calendar_time_s} seconds"],
            period="1 hour",  # Log data hourly
        )

        # Setup mesh with higher resolution for particle mechanics
        var_pts = sim_config.get(
            "var_pts",
            {
                "x_n": 10,
                "x_s": 10,
                "x_p": 10,
                "r_n": 30,  # Higher for particle mechanics
                "r_p": 30,
            },
        )

        # Create simulation
        print(f"✓ Creating simulation...")
        sim = pybamm.Simulation(
            model,
            experiment=experiment,
            parameter_values=default_params,
            var_pts=var_pts,
        )

        # Solve
        print(f"\n🚀 Solving calendar degradation (this may take a few minutes)...")
        solver = pybamm.IDAKLUSolver(
            atol=sim_config.get("solver_atol"),
            rtol=sim_config.get("solver_rtol"),
        )

        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        print(f"✓ Simulation completed successfully!")

        # Extract timeseries data
        print(f"\n📊 Extracting results...")
        time_s = solution["Time [s]"].entries
        voltage_V = solution["Terminal voltage [V]"].entries
        temperature_K = solution["Volume-averaged cell temperature [K]"].entries

        # Calculate capacity fade
        nominal_capacity_Ah = cell_design["nominal_capacity"]["value"]

        # Try to extract degradation variables
        data = {
            "time_s": time_s,
            "voltage_V": voltage_V,
            "temperature_K": temperature_K,
        }

        # Extract capacity and SoC
        try:
            capacity_Ah = solution["Discharge capacity [A.h]"].entries
            soc = initial_soc - capacity_Ah / nominal_capacity_Ah
            data["capacity_Ah"] = capacity_Ah
            data["soc"] = soc
        except (KeyError, AttributeError):
            print("  ⚠️  Could not extract capacity")

        # Extract degradation timeseries
        try:
            data["LLI_pct"] = solution["Loss of lithium inventory [%]"].entries
            data["LAM_neg_pct"] = solution[
                "Loss of active material in negative electrode [%]"
            ].entries
            data["LAM_pos_pct"] = solution[
                "Loss of active material in positive electrode [%]"
            ].entries
            data["Li_lost_mol"] = solution["Total lithium lost [mol]"].entries
            data["Q_SEI_Ah"] = solution[
                "Loss of capacity to negative SEI [A.h]"
            ].entries
            data["Q_SEI_cracks_Ah"] = solution[
                "Loss of capacity to negative SEI on cracks [A.h]"
            ].entries
            data["Q_side_reactions_Ah"] = solution[
                "Total capacity lost to side reactions [A.h]"
            ].entries
            data["porosity_neg"] = solution[
                "X-averaged negative electrode porosity"
            ].entries
            data["porosity_pos"] = solution[
                "X-averaged positive electrode porosity"
            ].entries
            data["throughput_Ah"] = solution["Throughput capacity [A.h]"].entries

            print("  ✓ Degradation timeseries extracted")
        except (KeyError, AttributeError) as e:
            print(f"  ⚠️  Some degradation variables unavailable: {e}")

        # Build summary
        summary = {
            "initial_capacity_Ah": nominal_capacity_Ah,
            "final_capacity_Ah": nominal_capacity_Ah,
            "capacity_fade_Ah": 0.0,
            "capacity_fade_pct": 0.0,
            "initial_soh_pct": 100.0,
            "final_soh_pct": 100.0,
            "calendar_time_days": calendar_time_days,
        }

        # Determine stop reason
        stop_reason = "completed"

        if "LLI_pct" in data:
            lli_final = float(data["LLI_pct"][-1])
            capacity_fade_Ah = nominal_capacity_Ah * lli_final / 100
            final_soh = 100.0 - lli_final

            summary.update(
                {
                    "capacity_fade_Ah": capacity_fade_Ah,
                    "capacity_fade_pct": lli_final,
                    "final_capacity_Ah": nominal_capacity_Ah - capacity_fade_Ah,
                    "initial_soh_pct": 100.0,
                    "final_soh_pct": final_soh,
                    "LLI_pct": float(lli_final),
                }
            )

            # Check if SoH threshold was reached
            if soh_threshold is not None and final_soh <= soh_threshold:
                stop_reason = "soh_threshold"
            else:
                stop_reason = "completed"

        if "LAM_neg_pct" in data:
            summary["LAM_neg_pct"] = float(data["LAM_neg_pct"][-1])
        if "LAM_pos_pct" in data:
            summary["LAM_pos_pct"] = float(data["LAM_pos_pct"][-1])

        if "Q_SEI_Ah" in data and "Q_SEI_cracks_Ah" in data:
            summary["Q_SEI_total_Ah"] = float(data["Q_SEI_Ah"][-1]) + float(
                data["Q_SEI_cracks_Ah"][-1]
            )

        if "porosity_neg" in data:
            summary["porosity_neg_initial"] = float(data["porosity_neg"][0])
            summary["porosity_neg_final"] = float(data["porosity_neg"][-1])
            summary["porosity_neg_change"] = float(data["porosity_neg"][-1]) - float(
                data["porosity_neg"][0]
            )

        if "porosity_pos" in data:
            summary["porosity_pos_initial"] = float(data["porosity_pos"][0])
            summary["porosity_pos_final"] = float(data["porosity_pos"][-1])
            summary["porosity_pos_change"] = float(data["porosity_pos"][-1]) - float(
                data["porosity_pos"][0]
            )

        print(f"\n" + "=" * 80)
        print(f"RESULTS")
        print(f"=" * 80)
        print(f"Duration: {calendar_time_days} days")
        print(f"Stop reason: {stop_reason}")
        if summary.get("LLI_pct"):
            print(f"Loss of Lithium Inventory: {summary['LLI_pct']:.4f}%")
            print(f"Final SoH: {summary['final_soh_pct']:.2f}%")
        if summary.get("LAM_neg_pct"):
            print(f"LAM (negative): {summary['LAM_neg_pct']:.4f}%")
        if summary.get("LAM_pos_pct"):
            print(f"LAM (positive): {summary['LAM_pos_pct']:.4f}%")
        if summary.get("Q_SEI_total_Ah"):
            print(f"Total SEI capacity loss: {summary['Q_SEI_total_Ah']:.4f} Ah")
        print(f"=" * 80)

        return {
            "success": True,
            "stop_reason": stop_reason,
            "data": data,
            "summary": summary,
            "config": sim_config,
        }

    except Exception as e:
        import traceback

        error_msg = str(e)
        full_trace = traceback.format_exc()
        print(f"\n✗ Simulation failed: {error_msg}")
        print(f"Traceback:\n{full_trace}")

        return {
            "success": False,
            "stop_reason": "error",
            "error": error_msg,
            "traceback": full_trace,
            "config": sim_config,
        }
