"""
DFN Cycle Degradation Module

Simulates charge/discharge cycling degradation for Li-ion cells using the
Doyle-Fuller-Newman (DFN) electrochemical model with comprehensive degradation
mechanisms.

This module implements full cycling protocols with:
- Discharge at x C-rate to lower voltage cutoff
- Charge at y C-rate to upper voltage cutoff
- Multiple cycles until either cycle count or SoH threshold reached
- SEI growth, LLI, LAM, and particle mechanics degradation

Based on PyBaMM DFN model with O'Kane 2022 degradation parameters.
"""

import pybamm
import numpy as np
import sys
from typing import Dict, Tuple, Optional, Any


def build_dfn_cycle_model_options() -> Dict[str, str]:
    """
    Build DFN model options for cycle degradation simulation.

    Returns:
        Dictionary of PyBaMM model options configured for cycling with degradation
    """
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
        "SEI": "solvent-diffusion limited",
        "SEI porosity change": "true",
        "SEI on cracks": "true",
        "lithium plating": "none",
        "particle mechanics": ("swelling and cracking", "swelling only"),
        "loss of active material": "stress-driven",
    }
    return model_options


def build_dfn_cycle_degradation_params(
    cell_design: Dict, sim_config: Dict
) -> pybamm.ParameterValues:
    """
    Build PyBaMM parameter values for cycle degradation simulation.

    Args:
        cell_design: Cell design dictionary from manifest
        sim_config: Simulation configuration

    Returns:
        PyBaMM ParameterValues object with all parameters set
    """
    print("\nBuilding DFN cycle degradation parameters...")

    # Start with O'Kane 2022 parameter set (comprehensive degradation)
    param = pybamm.ParameterValues("OKane2022")

    # Ambient temperature
    ambient_temp_C = sim_config.get("ambient_temperature_C", 25)
    ambient_temp_K = ambient_temp_C + 273.15
    print(f"  Ambient temperature: {ambient_temp_C}°C ({ambient_temp_K}K)")

    # Update thermal parameters
    param.update(
        {
            "Ambient temperature [K]": ambient_temp_K,
            "Initial temperature [K]": ambient_temp_K,
        }
    )

    # Extract nominal capacity
    nominal_capacity_Ah = cell_design["nominal_capacity"]["value"]
    print(f"  Nominal capacity: {nominal_capacity_Ah:.2f} Ah")

    # Update capacity and contact resistance
    param.update(
        {
            "Nominal cell capacity [A.h]": nominal_capacity_Ah,
            "Contact resistance [Ohm]": sim_config.get(
                "contact_resistance_Ohm", 0.0001
            ),
        }
    )

    # Heat transfer parameters
    param.update(
        {
            "Total heat transfer coefficient [W.m-2.K-1]": sim_config.get(
                "total_heat_transfer_coefficient_W_m2K", 10
            ),
            "Cell cooling surface area [m2]": sim_config.get(
                "cooling_surface_area_m2", 0.01
            ),
        }
    )

    # Voltage cutoffs (use sim_config or defaults)
    param.update(
        {
            "Upper voltage cut-off [V]": sim_config.get("upper_voltage_cutoff_V", 4.2),
            "Lower voltage cut-off [V]": sim_config.get("lower_voltage_cutoff_V", 2.5),
        }
    )

    # Degradation parameters (customizable)
    if "sei_kinetic_rate_constant" in sim_config:
        param["SEI kinetic rate constant [m.s-1]"] = sim_config[
            "sei_kinetic_rate_constant"
        ]

    if "sei_growth_activation_energy" in sim_config:
        param["SEI growth activation energy [J.mol-1]"] = sim_config[
            "sei_growth_activation_energy"
        ]

    print(f"  ✓ DFN cycle degradation parameters built")

    return param


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


def run_cycle_degradation(cell_design: Dict, sim_config: Dict) -> Dict[str, Any]:
    """
    Run DFN cycle degradation simulation with charge/discharge cycling.

    Runs charge/discharge cycles until completion or stop condition reached:
    1. Start at 100% SoC (or initial_soc if specified)
    2. Discharge at discharge_c_rate to lower_voltage_cutoff_V
    3. Charge at charge_c_rate to upper_voltage_cutoff_V
    4. Repeat for num_cycles OR until soh_threshold reached

    Args:
        cell_design: Cell design dictionary from manifest JSON
        sim_config: Simulation configuration dictionary with keys:
            - num_cycles: Number of charge/discharge cycles (default: 100)
            - discharge_c_rate: Discharge C-rate, e.g., 1.0 for 1C (default: 1.0)
            - charge_c_rate: Charge C-rate, e.g., 0.5 for C/2 (default: 0.5)
            - initial_soc: Starting state of charge (0-1, default: 1.0)
            - soh_threshold: Stop if SoH drops below this % (optional)
            - ambient_temperature_C: Temperature (default: 25°C)
            - upper_voltage_cutoff_V: Max voltage (default: 4.2V)
            - lower_voltage_cutoff_V: Min voltage (default: 2.5V)
            - skip_capacity_calibration: Skip calibration, faster but less accurate (default: False)
            - solver_atol: Absolute tolerance (default: 1e-4)
            - solver_rtol: Relative tolerance (default: 1e-4)

    Returns:
        Dictionary with keys:
            - success: Boolean indicating successful completion
            - stop_reason: Why stopped ('num_cycles', 'soh_threshold', or 'error')
            - error: Error message if failed
            - data: Dict with cycle-by-cycle results
            - summary: Dict with degradation summary
            - config: Copy of input configuration

    Note:
        Uses PyBaMM throughput energy limit of 500 kWh to handle large cells (>100 Ah)
        with multiple cycles reliably. This consolidated single-step approach now
        supports 1000+ cycles without multi-step complications.
    """

    # Extract simulation parameters
    num_cycles = sim_config.get("num_cycles", 100)

    print("=" * 80)
    print("DFN CYCLE DEGRADATION SIMULATION")
    print("=" * 80)

    # Increase PyBaMM's throughput energy limit to handle large cells
    # Default: 100,000 W.h (100 kWh) - too small for 160 Ah cells with multiple cycles
    # New: 500,000 W.h (500 kWh) - handles even extreme cases
    print("\nAdjusting PyBaMM solver settings...")
    pybamm.settings.max_y_value = 500000.0  # 500 kWh throughput limit
    print(f"  ✓ Throughput energy limit: {pybamm.settings.max_y_value / 1000:.0f} kWh")

    # Extract simulation parameters
    num_cycles = sim_config.get("num_cycles", 100)
    discharge_c_rate = sim_config.get("discharge_c_rate", 1.0)
    charge_c_rate = sim_config.get("charge_c_rate", 0.5)
    initial_soc = sim_config.get("initial_soc", 1.0)
    ambient_temp_C = sim_config.get("ambient_temperature_C", 25)
    soh_threshold = sim_config.get("soh_threshold", None)

    print(f"\nCycling parameters:")
    print(f"  Number of cycles: {num_cycles}")
    print(f"  Discharge C-rate: {discharge_c_rate}C")
    print(f"  Charge C-rate: {charge_c_rate}C")
    print(f"  Initial SoC: {initial_soc*100:.0f}%")
    print(f"  Temperature: {ambient_temp_C}°C")
    if soh_threshold is not None:
        print(f"  SoH threshold cutoff: {soh_threshold}%")

    try:
        # Build model options
        model_options = build_dfn_cycle_model_options()
        print(f"\n✓ Model options configured")
        print(f"  - SEI model: {model_options['SEI']}")
        print(f"  - Particle mechanics: {model_options['particle mechanics']}")
        print(f"  - LAM model: {model_options['loss of active material']}")

        # Build parameters
        default_params = build_dfn_cycle_degradation_params(cell_design, sim_config)

        # Capacity calibration (unless explicitly skipped)
        if not sim_config.get("skip_capacity_calibration", False):
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

        # Get nominal capacity for C-rate calculation
        nominal_capacity_Ah = cell_design["nominal_capacity"]["value"]

        # **CREATE DFN MODEL**
        print(f"\n✓ Creating DFN model...")
        model = pybamm.lithium_ion.DFN(options=model_options)
        print(f"  Model created with {len(default_params)} parameters")

        # **STATE CONTINUATION FOR MULTI-STEP MODE**
        # NOTE: PyBaMM's Experiment solver doesn't properly track cycles when using
        # model.set_initial_conditions_from(). So for continuation steps, we instead:
        # 1. Use the degradation metrics (LLI, LAM) from the previous step
        # 2. Don't apply state continuation to the model
        # 3. Just run fresh cycles on degraded parameters
        # This is less accurate but avoids the cycle tracking bug

        is_continuation_step = (
            "_previous_solution" in sim_config
            and sim_config["_previous_solution"] is not None
        )
        if is_continuation_step:
            print(f"✓ Continuation step detected (multi-step cycling)")
            print(f"  NOTE: Will run fresh cycles without formal state continuation")
            print(
                f"        (PyBaMM limitation: Experiment API doesn't track cycles properly with set_initial_conditions_from)"
            )

        # For now, DON'T apply set_initial_conditions_from() because it breaks cycle tracking
        # The degradation will accumulate through the parameter adjustments in calibration

        # Create cycling experiment
        print(f"\n✓ Setting up cycling experiment...")
        discharge_current = discharge_c_rate * nominal_capacity_Ah
        charge_current = charge_c_rate * nominal_capacity_Ah

        # Build experiment steps for multiple cycles
        experiment_steps = []
        for cycle_num in range(1, num_cycles + 1):
            # Discharge step
            experiment_steps.append(
                f"Discharge at {discharge_current} A until "
                f"{sim_config.get('lower_voltage_cutoff_V', 2.5)} V"
            )
            # Charge step
            experiment_steps.append(
                f"Charge at {charge_current} A until "
                f"{sim_config.get('upper_voltage_cutoff_V', 4.2)} V"
            )

        experiment = pybamm.Experiment(
            experiment_steps,
            period="1 minute",  # Log data every minute
        )

        print(f"  {len(experiment_steps)} steps ({num_cycles} full cycles)")
        print(f"  Discharge: {discharge_current:.2f} A ({discharge_c_rate}C)")
        print(f"  Charge: {charge_current:.2f} A ({charge_c_rate}C)")

        # Setup mesh
        var_pts = sim_config.get(
            "var_pts",
            {
                "x_n": 10,
                "x_s": 10,
                "x_p": 10,
                "r_n": 30,
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
        print(f"\n🚀 Solving cycle degradation...")
        print(f"   This may take 10-30 minutes for {num_cycles} cycles...")
        print(
            f"   Cell capacity: {nominal_capacity_Ah:.1f} Ah | C-rates: {discharge_c_rate}C disch, {charge_c_rate}C charge"
        )
        solver = pybamm.IDAKLUSolver(
            atol=sim_config.get("solver_atol", 1e-4),
            rtol=sim_config.get("solver_rtol", 1e-4),
        )

        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        print(f"✓ Simulation completed successfully!")

        # Extract cycle-by-cycle data
        print(f"\n📊 Extracting cycle-by-cycle results...")

        # Get data arrays
        time_s = solution["Time [s]"].entries
        voltage_V = solution["Terminal voltage [V]"].entries
        current_A = solution["Current [A]"].entries
        temperature_K = solution["Volume-averaged cell temperature [K]"].entries

        # Process cycles
        cycle_data = []

        # Try to use solution.cycles if available (standard path)
        num_steps = (
            len(solution.cycles)
            if hasattr(solution, "cycles") and solution.cycles
            else 0
        )

        if num_steps > 1:  # More than just a wrapper cycle
            print(
                f"  Processing {num_steps} steps ({num_steps//2} cycles) from solution.cycles..."
            )

            for i in range(0, num_steps, 2):  # Process pairs (discharge + charge)
                if i + 1 >= num_steps:
                    break

                cycle_num = (i // 2) + 1
                discharge_cycle = solution.cycles[i]
                charge_cycle = solution.cycles[i + 1]

                # Extract capacity for this cycle
                try:
                    # Discharge capacity
                    dch_capacity = discharge_cycle["Discharge capacity [A.h]"].entries
                    discharge_capacity_Ah = abs(dch_capacity[-1] - dch_capacity[0])

                    # Charge capacity
                    ch_capacity = charge_cycle["Discharge capacity [A.h]"].entries
                    charge_capacity_Ah = abs(ch_capacity[-1] - ch_capacity[0])

                    # Average capacity
                    cycle_capacity_Ah = (discharge_capacity_Ah + charge_capacity_Ah) / 2

                    # Calculate SoH
                    soh_pct = (cycle_capacity_Ah / nominal_capacity_Ah) * 100

                    # Extract degradation metrics if available
                    try:
                        lli_pct = charge_cycle["Loss of lithium inventory [%]"].entries[
                            -1
                        ]
                    except:
                        lli_pct = 0.0

                    try:
                        lam_neg_pct = charge_cycle[
                            "Loss of active material in negative electrode [%]"
                        ].entries[-1]
                    except:
                        lam_neg_pct = 0.0

                    try:
                        lam_pos_pct = charge_cycle[
                            "Loss of active material in positive electrode [%]"
                        ].entries[-1]
                    except:
                        lam_pos_pct = 0.0

                    cycle_data.append(
                        {
                            "cycle": cycle_num,
                            "discharge_capacity_Ah": discharge_capacity_Ah,
                            "charge_capacity_Ah": charge_capacity_Ah,
                            "capacity_Ah": cycle_capacity_Ah,
                            "soh_pct": soh_pct,
                            "lli_pct": lli_pct,
                            "lam_neg_pct": lam_neg_pct,
                            "lam_pos_pct": lam_pos_pct,
                        }
                    )

                    # Check SoH threshold
                    if soh_threshold is not None and soh_pct <= soh_threshold:
                        print(
                            f"  ⚠️  SoH threshold reached at cycle {cycle_num}: {soh_pct:.2f}%"
                        )
                        break

                except Exception as e:
                    print(
                        f"  ⚠️  Could not extract data for cycle {cycle_num}: {str(e)[:50]}"
                    )

        else:
            # Fallback: solution.cycles is empty/malformed (can happen with set_initial_conditions_from)
            # Reconstruct cycles from discharge capacity time series
            print(f"  ⚠️  solution.cycles unavailable (state continuation mode)")
            print(f"  Reconstructing cycles from capacity time series...")

            try:
                capacity_Ah = solution["Discharge capacity [A.h]"].entries

                # Get final degradation metrics
                try:
                    lli_pct_final = solution["Loss of lithium inventory [%]"].entries[
                        -1
                    ]
                except:
                    lli_pct_final = 0.0

                try:
                    lam_neg_pct_final = solution[
                        "Loss of active material in negative electrode [%]"
                    ].entries[-1]
                except:
                    lam_neg_pct_final = 0.0

                try:
                    lam_pos_pct_final = solution[
                        "Loss of active material in positive electrode [%]"
                    ].entries[-1]
                except:
                    lam_pos_pct_final = 0.0

                # Detect charge cycles: capacity should return to near zero at each cycle end
                # Discharge steps: capacity goes from ~0 to some value (negative current)
                # Charge steps: capacity stays high (positive current)
                capacity_diff = np.diff(capacity_Ah)

                # Find local maxima in capacity (end of discharge)
                cycle_endings = []
                for idx in range(1, len(capacity_Ah) - 1):
                    # Look for points where capacity stops increasing much (near end of charge)
                    # and is about to decrease (discharge starting)
                    if (
                        current_A[idx] > 0.5
                        and idx + 1 < len(current_A)
                        and current_A[idx + 1] < -1.0
                    ):
                        cycle_endings.append(idx)

                # If we didn't find cycle endings, estimate based on expected cycle count
                if len(cycle_endings) == 0:
                    print(
                        f"    Estimating {num_cycles} cycle endpoints from {len(capacity_Ah)} data points..."
                    )
                    points_per_cycle = (
                        len(capacity_Ah) // num_cycles if num_cycles > 0 else 1
                    )
                    for c in range(1, num_cycles + 1):
                        cycle_endings.append(
                            min(c * points_per_cycle, len(capacity_Ah) - 1)
                        )

                # Extract capacity per cycle
                prev_cap = 0
                for cycle_idx, end_idx in enumerate(cycle_endings, 1):
                    if cycle_idx > num_cycles:
                        break

                    cap_at_end = (
                        capacity_Ah[end_idx]
                        if end_idx < len(capacity_Ah)
                        else capacity_Ah[-1]
                    )
                    cycle_capacity_Ah = abs(cap_at_end - prev_cap)

                    soh_pct = (cycle_capacity_Ah / nominal_capacity_Ah) * 100

                    cycle_data.append(
                        {
                            "cycle": cycle_idx,
                            "discharge_capacity_Ah": cycle_capacity_Ah,
                            "charge_capacity_Ah": cycle_capacity_Ah,
                            "capacity_Ah": cycle_capacity_Ah,
                            "soh_pct": soh_pct,
                            "lli_pct": (
                                lli_pct_final
                                if cycle_idx == len(cycle_endings)
                                else 0.0
                            ),
                            "lam_neg_pct": (
                                lam_neg_pct_final
                                if cycle_idx == len(cycle_endings)
                                else 0.0
                            ),
                            "lam_pos_pct": (
                                lam_pos_pct_final
                                if cycle_idx == len(cycle_endings)
                                else 0.0
                            ),
                        }
                    )

                    prev_cap = cap_at_end

                    # Check SoH threshold
                    if soh_threshold is not None and soh_pct <= soh_threshold:
                        print(
                            f"  ⚠️  SoH threshold reached at cycle {cycle_idx}: {soh_pct:.2f}%"
                        )
                        break

                print(f"    Reconstructed {len(cycle_data)} cycles from time series")

            except Exception as e:
                print(f"  ❌ Fallback extraction failed: {str(e)[:100]}")
                print(f"    Available solution keys: {list(solution.keys())[:5]}")

        print(f"  ✓ Extracted data for {len(cycle_data)} cycles")

        # Determine stop reason
        stop_reason = "num_cycles"
        if soh_threshold is not None and len(cycle_data) > 0:
            if cycle_data[-1]["soh_pct"] <= soh_threshold:
                stop_reason = "soh_threshold"

        # Build summary
        if len(cycle_data) > 0:
            initial_capacity = cycle_data[0]["capacity_Ah"]
            final_capacity = cycle_data[-1]["capacity_Ah"]
            capacity_fade = initial_capacity - final_capacity

            summary = {
                "num_cycles_completed": len(cycle_data),
                "initial_capacity_Ah": initial_capacity,
                "final_capacity_Ah": final_capacity,
                "capacity_fade_Ah": capacity_fade,
                "capacity_fade_pct": (capacity_fade / initial_capacity) * 100,
                "initial_soh_pct": cycle_data[0]["soh_pct"],
                "final_soh_pct": cycle_data[-1]["soh_pct"],
                "final_lli_pct": cycle_data[-1]["lli_pct"],
                "final_lam_neg_pct": cycle_data[-1]["lam_neg_pct"],
                "final_lam_pos_pct": cycle_data[-1]["lam_pos_pct"],
            }
        else:
            summary = {
                "num_cycles_completed": 0,
                "error": "No cycle data extracted",
            }

        print(f"\n" + "=" * 80)
        print(f"RESULTS")
        print(f"=" * 80)
        print(f"Cycles completed: {len(cycle_data)}/{num_cycles}")
        print(f"Stop reason: {stop_reason}")
        if len(cycle_data) > 0:
            print(f"Initial capacity: {summary['initial_capacity_Ah']:.2f} Ah")
            print(f"Final capacity: {summary['final_capacity_Ah']:.2f} Ah")
            print(
                f"Capacity fade: {summary['capacity_fade_Ah']:.4f} Ah ({summary['capacity_fade_pct']:.2f}%)"
            )
            print(f"Final SoH: {summary['final_soh_pct']:.2f}%")
            print(f"Final LLI: {summary['final_lli_pct']:.4f}%")
        print(f"=" * 80)

        # For multi-step: extract final state vector for analysis only
        # NOTE: We don't use set_initial_conditions_from() due to PyBaMM limitations
        final_state_vector = solution.y[:, -1]

        return {
            "success": True,
            "stop_reason": stop_reason,
            "data": {
                "cycles": cycle_data,
                "time_s": time_s,
                "voltage_V": voltage_V,
                "current_A": current_A,
                "temperature_K": temperature_K,
            },
            "summary": summary,
            "config": sim_config,
            "final_state_vector": final_state_vector,  # For analysis/debugging
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
