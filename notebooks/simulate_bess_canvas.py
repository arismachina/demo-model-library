"""
BESS Duty Cycle Simulation
Runs PyBaMM simulations for all duty cycles against active cell designs
"""

import pybamm
import numpy as np

# ============================================================================
# PYBAMM DRIVE CYCLE SIMULATION MODULE
# ============================================================================


def _build_pybamm_params(cell_design: dict, simulation_config: dict) -> tuple:
    """Build PyBaMM parameters from cell design manifest."""

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
        "Positive electrode specific heat capacity [J.kg-1.K-1]": 700,
    }

    positive_cc_params = {
        "Positive current collector thickness [m]": pos_electrode["foil"]["thickness"][
            "value"
        ]
        / 1e6,
        "Positive current collector conductivity [S.m-1]": pos_electrode["foil"][
            "material"
        ]["electrical_conductivity"]["value"],
        "Positive current collector density [kg.m-3]": pos_electrode["foil"][
            "material"
        ]["density"]["value"]
        * 1000,
        "Positive current collector specific heat capacity [J.kg-1.K-1]": 897,
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
        "Negative electrode specific heat capacity [J.kg-1.K-1]": 700,
    }

    negative_cc_params = {
        "Negative current collector thickness [m]": neg_electrode["foil"]["thickness"][
            "value"
        ]
        / 1e6,
        "Negative current collector conductivity [S.m-1]": neg_electrode["foil"][
            "material"
        ]["electrical_conductivity"]["value"],
        "Negative current collector density [kg.m-3]": neg_electrode["foil"][
            "material"
        ]["density"]["value"]
        * 1000,
        "Negative current collector specific heat capacity [J.kg-1.K-1]": 385,
    }

    # Separator parameters
    separator = cell_design["separator"]
    separator_params = {
        "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
        "Separator porosity": separator["porosity"]["value"],
        "Separator density [kg.m-3]": separator["material"]["density"]["value"] * 1000,
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

        sol_capacity = sim_capacity.solve(
            solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
        )

        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            break

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah
        error_percent = abs(1 - scale_factor) * 100

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


def _run_pybamm_drive_cycle(
    drive_cycle: dict,
    simulation_config: dict,
    default_params: pybamm.ParameterValues,
    model_options: dict,
) -> dict:
    """Execute PyBaMM simulation for drive cycle."""

    time_s = np.array(drive_cycle["time_s"])
    label = drive_cycle.get("label", "drive_cycle")

    # Determine drive cycle type: power_W
    values = np.array(drive_cycle["power_W"])
    drive_data = np.column_stack((time_s, values))
    drive_cycle_step = pybamm.step.power(drive_data, duration=time_s[-1])

    period = simulation_config.get("period", "10 second")
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
        ],
    )

    sim = pybamm.Simulation(
        model,
        parameter_values=default_params,
        experiment=experiment,
        var_pts=var_pts,
    )

    initial_soc = simulation_config.get("initial_soc", 0.5)

    solution = sim.solve(initial_soc=initial_soc, solver=solver)

    soc = (
        initial_soc
        - solution["Discharge capacity [A.h]"].entries
        / default_params["Nominal cell capacity [A.h]"]
    )

    result = {
        "time_s": solution["Time [s]"].entries.tolist(),
        "voltage_V": solution["Terminal voltage [V]"].entries.tolist(),
        "current_A": solution["Current [A]"].entries.tolist(),
        "temperature_K": solution[
            "Volume-averaged cell temperature [K]"
        ].entries.tolist(),
        "capacity_Ah": solution["Discharge capacity [A.h]"].entries.tolist(),
        "energy_Wh": solution["Discharge energy [W.h]"].entries.tolist(),
        "power_W": solution["Terminal power [W]"].entries.tolist(),
        "soc": soc.tolist(),
        "anode_potential_V": solution["Anode potential [V]"].entries.tolist(),
        "experiment_label": label,
        "success": True,
    }

    return result


def run_drive_cycle(cell_design: dict, simulation_config: dict) -> dict:
    """Run a drive cycle simulation with comprehensive analysis."""

    # Build PyBaMM parameters and run capacity calibration
    default_params, model_options = _build_pybamm_params(
        cell_design, simulation_config
    )

    # Run simulation
    sim_result = _run_pybamm_drive_cycle(
        drive_cycle=simulation_config["drive_cycle"],
        simulation_config=simulation_config,
        default_params=default_params,
        model_options=model_options,
    )

    if not sim_result.get("success", False):
        return {
            "success": False,
            "error": sim_result.get("error", "Unknown error"),
        }

    # Extract summary statistics
    sim_time = np.array(sim_result["time_s"])
    sim_capacity = np.array(sim_result["capacity_Ah"])
    sim_energy = np.array(sim_result["energy_Wh"])
    sim_temp = np.array(sim_result["temperature_K"])
    sim_voltage = np.array(sim_result["voltage_V"])
    sim_soc = np.array(sim_result["soc"])

    summary = {
        "duration_min": float((sim_time[-1] - sim_time[0]) / 60),
        "capacity_used_Ah": float(sim_capacity[-1] - sim_capacity[0]),
        "energy_used_Wh": float(sim_energy[-1] - sim_energy[0]),
        "temperature_max_C": float(sim_temp.max() - 273.15),
        "temperature_rise_C": float(sim_temp.max() - sim_temp[0]),
        "voltage_min_V": float(sim_voltage.min()),
        "voltage_max_V": float(sim_voltage.max()),
        "final_soc": float(sim_soc[-1]),
    }

    return {
        "success": True,
        "summary": summary,
        "timeseries": {
            "time_s": sim_result["time_s"],
            "voltage_V": sim_result["voltage_V"],
            "current_A": sim_result["current_A"],
            "temperature_K": sim_result["temperature_K"],
            "temperature_C": [
                float(t - 273.15) for t in sim_result["temperature_K"]
            ],
            "capacity_Ah": sim_result["capacity_Ah"],
            "energy_Wh": sim_result["energy_Wh"],
            "power_W": sim_result["power_W"],
            "soc": sim_result["soc"],
            "anode_potential_V": sim_result["anode_potential_V"],
        },
    }


# ============================================================================
# MAIN CALCULATION
# ============================================================================

# Get inputs
cell_data = componentInputs.get("Cell Design Input", {})
peak_shaving = componentInputs.get("Peak Shaving Duty Cycle Parser", {})
capacity_firming = componentInputs.get("Capacity Firming Duty Cycle Parser", {})
energy_firming = componentInputs.get("Energy Firming Duty Cycle Parser", {})
freq_reg = componentInputs.get("Frequency Regulation Duty Cycle Parser", {})

# Pack parameters
max_power_kW = componentInputs.get("Pack Max Power (kW)", 1000)
cells_parallel = componentInputs.get("Cells in Parallel", 100)
max_duration_min = componentInputs.get("Max Duration (minutes)", 60)

# Simulation parameters
ambient_temp_K = componentInputs.get("Ambient Temperature (K)", 298.15)
initial_soc = componentInputs.get("Initial SOC", 0.5)
heat_transfer_coef = componentInputs.get("Heat Transfer Coefficient", 15)
cooling_area_m2 = componentInputs.get("Cooling Surface Area (m2)", 0.05)

# Build duty cycles dictionary
cycles = {
    "Peak Shaving": peak_shaving,
    "Capacity Firming": capacity_firming,
    "Energy Firming": energy_firming,
    "Frequency Regulation": freq_reg,
}

# Check if we have cell designs
if not cell_data:
    result = {
        "status": "no_cell_designs",
        "message": "No active cell designs found. Please add a cell design to the project.",
        "num_cycles": len([c for c in cycles.values() if c]),
    }
else:
    # Run simulations for each cell design and duty cycle
    simulation_results = {}

    for design_id, d in cell_data.items():
        # Build cell_design dict from input component data
        cell_design = {
            "nominal_capacity": {"value": d.get("kpis.nominal_capacity.value")},
                "nominal_energy": {"value": d.get("kpis.nominal_energy.value")},
                "upper_voltage_cutoff": {
                    "value": d.get("cell_design.upper_voltage_cutoff.value")
                },
                "lower_voltage_cutoff": {
                    "value": d.get("cell_design.lower_voltage_cutoff.value")
                },
                "cell_volume": {"value": d.get("kpis.cell_volume.value")},
                "positive_electrode": {
                    "count": {
                        "value": d.get("cell_design.positive_electrode.count.value")
                    },
                    "height": {
                        "value": d.get("cell_design.positive_electrode.height.value")
                    },
                    "width": {
                        "value": d.get("cell_design.positive_electrode.width.value")
                    },
                    "coating": {
                        "thickness": {
                            "value": d.get(
                                "cell_design.positive_electrode.coating.thickness.value"
                            )
                        },
                        "porosity": {
                            "value": d.get(
                                "cell_design.positive_electrode.coating.porosity.value"
                            )
                        },
                        "density": {
                            "value": d.get(
                                "cell_design.positive_electrode.coating.density.value"
                            )
                        },
                        "active_material_volume_fraction": {
                            "value": d.get(
                                "cell_design.positive_electrode.coating.active_material_volume_fraction.value"
                            )
                        },
                        "formulation": {
                            "primary_active_material": {
                                "name": d.get(
                                    "cell_design.positive_electrode.coating.formulation.primary_active_material.name"
                                )
                            }
                        },
                    },
                    "foil": {
                        "thickness": {
                            "value": d.get(
                                "cell_design.positive_electrode.foil.thickness.value"
                            )
                        },
                        "material": {
                            "density": {
                                "value": d.get(
                                    "cell_design.positive_electrode.foil.material.density.value"
                                )
                            },
                            "electrical_conductivity": {
                                "value": d.get(
                                    "cell_design.positive_electrode.foil.material.electrical_conductivity.value"
                                )
                            },
                        },
                    },
                },
                "negative_electrode": {
                    "height": {
                        "value": d.get("cell_design.negative_electrode.height.value")
                    },
                    "width": {
                        "value": d.get("cell_design.negative_electrode.width.value")
                    },
                    "coating": {
                        "thickness": {
                            "value": d.get(
                                "cell_design.negative_electrode.coating.thickness.value"
                            )
                        },
                        "porosity": {
                            "value": d.get(
                                "cell_design.negative_electrode.coating.porosity.value"
                            )
                        },
                        "density": {
                            "value": d.get(
                                "cell_design.negative_electrode.coating.density.value"
                            )
                        },
                        "active_material_volume_fraction": {
                            "value": d.get(
                                "cell_design.negative_electrode.coating.active_material_volume_fraction.value"
                            )
                        },
                    },
                    "foil": {
                        "thickness": {
                            "value": d.get(
                                "cell_design.negative_electrode.foil.thickness.value"
                            )
                        },
                        "material": {
                            "density": {
                                "value": d.get(
                                    "cell_design.negative_electrode.foil.material.density.value"
                                )
                            },
                            "electrical_conductivity": {
                                "value": d.get(
                                    "cell_design.negative_electrode.foil.material.electrical_conductivity.value"
                                )
                            },
                        },
                    },
                },
                "separator": {
                    "thickness": {
                        "value": d.get("cell_design.separator.thickness.value")
                    },
                    "porosity": {
                        "value": d.get("cell_design.separator.porosity.value")
                    },
                    "material": {
                        "density": {
                            "value": d.get(
                                "cell_design.separator.material.density.value"
                            )
                        }
                    },
                },
                "jelly_roll": {
                    "count": {"value": d.get("cell_design.jelly_roll.count.value")}
                },
        }

        design_results = {}

        for cycle_name, cycle_data in cycles.items():
            if not cycle_data or "power_per_unit" not in cycle_data:
                continue

            # Prepare drive cycle data
            time_min = np.array(cycle_data["time_minutes"])
            power_pu = np.array(cycle_data["power_per_unit"])

            # Limit to max duration
            mask = time_min <= max_duration_min
            time_min = time_min[mask]
            power_pu = power_pu[mask]

            # Convert to seconds
            time_s = time_min * 60

            # Convert per-unit power to cell power (W)
            pack_power_W = power_pu * max_power_kW * 1000
            cell_power_W = pack_power_W / cells_parallel

            # Build simulation config
            simulation_config = {
                "ambient_temperature": ambient_temp_K,
                "initial_temperature": ambient_temp_K,
                "initial_soc": initial_soc,
                "upper_voltage_cutoff": d.get(
                    "cell_design.upper_voltage_cutoff.value", 4.2
                ),
                "lower_voltage_cutoff": d.get(
                    "cell_design.lower_voltage_cutoff.value", 2.8
                ),
                "contact_resistance": 0.0001,
                "total_heat_transfer_coefficient": heat_transfer_coef,
                "cooling_surface_area": cooling_area_m2,
                "period": "10 second",
                "drive_cycle": {
                    "time_s": time_s.tolist(),
                    "power_W": cell_power_W.tolist(),
                    "label": cycle_name,
                },
            }

            # Run simulation
            sim_result = run_drive_cycle(cell_design, simulation_config)
            design_results[cycle_name] = sim_result

        simulation_results[design_id] = design_results

    result = {
        "status": "simulations_complete",
        "num_designs": len(simulation_results),
        "num_cycles": len([c for c in cycles.values() if c]),
        "simulation_results": simulation_results,
    }

result
