"""
SPMeT Drive Cycle Simulation - Multiple Designs
Supports custom termination conditions for anode potential and temperature limits.
"""

import pybamm
import numpy as np

# Get all inputs from upstream components
cell_design_data = componentInputs.get("Cell Design Data", {})
drive_cycle_data = componentInputs.get("Drive Cycle Data", {})

# Get simulation parameters
ambient_temp = componentInputs.get("Ambient Temperature [K]")
initial_temp = componentInputs.get("Initial Temperature [K]")
initial_soc = componentInputs.get("Initial SOC")
contact_resistance = componentInputs.get("Contact Resistance [Ohm]")
heat_transfer_coeff = componentInputs.get("Total Heat Transfer Coefficient [W.m-2.K-1]")
cooling_area = componentInputs.get("Cooling Surface Area [m2]")
min_soc = componentInputs.get("Minimum SOC")
max_soc = componentInputs.get("Maximum SOC")

# Pack configuration
pack_energy_kWh = componentInputs.get("Pack Energy [kWh]")
pack_nominal_voltage_V = componentInputs.get("Pack Nominal Voltage [V]")
pack_peak_power_kW = componentInputs.get("Pack Peak Power [kW]")


# Run simulation function (embedded)
def run_drive_cycle(cell_design, simulation_config):
    """Run drive cycle simulation - embedded version"""

    drive_cycle = simulation_config["drive_cycle"]
    pack_power_W = np.array(drive_cycle["power_W"])
    pack_nominal_voltage = simulation_config["pack_nominal_voltage_V"]
    pack_energy_kWh = simulation_config["pack_energy_kWh"]
    pack_peak_power_kW = simulation_config["pack_peak_power_kW"]
    nominal_capacity = cell_design["nominal_capacity"]["value"]
    nominal_energy = cell_design["nominal_energy"]["value"]
    cell_nominal_voltage = cell_design["nominal_voltage"]["value"]
    cells_series = pack_nominal_voltage / cell_nominal_voltage
    cells_parallel = pack_energy_kWh * 1000 / (nominal_energy * cells_series)
    cell_power_W = (
        pack_power_W
        / np.ceil(np.max(np.abs(pack_power_W)))
        * pack_peak_power_kW
        * 1000
        / (cells_parallel * cells_series)
    )
    drive_cycle = {**drive_cycle, "power_W": cell_power_W}
    simulation_config = {**simulation_config, "drive_cycle": drive_cycle}

    # Select base parameter set
    cathode_material = cell_design["positive_electrode"]["coating"]["formulation"][
        "primary_active_material"
    ]["name"]

    if "LFP" in cathode_material.upper():
        default_params = pybamm.ParameterValues("Prada2013")
    else:
        default_params = pybamm.ParameterValues("ORegan2022")

    # Build PyBaMM parameters
    number_of_coated_sides = 2
    pos_electrode = cell_design["positive_electrode"]
    neg_electrode = cell_design["negative_electrode"]
    separator = cell_design["separator"]

    pybamm_params = {
        "Nominal cell capacity [A.h]": cell_design["nominal_capacity"]["value"],
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
        "Positive current collector specific heat capacity [J.kg-1.K-1]": 897,
        "Negative current collector specific heat capacity [J.kg-1.K-1]": 385,
        "Positive electrode specific heat capacity [J.kg-1.K-1]": 700,
        "Negative electrode specific heat capacity [J.kg-1.K-1]": 700,
        "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
        "Separator porosity": separator["porosity"]["value"],
        "Separator density [kg.m-3]": separator["material"]["physical_properties"][
            "density"
        ]["value"]
        * 1000,
        "Separator specific heat capacity [J.kg-1.K-1]": 700,
        "Reference temperature [K]": 298.15,
        "Total heat transfer coefficient [W.m-2.K-1]": simulation_config[
            "total_heat_transfer_coefficient"
        ],
        "Cell cooling surface area [m2]": simulation_config["cooling_surface_area"],
        "Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
        "Ambient temperature [K]": simulation_config["ambient_temperature"],
        "Initial temperature [K]": simulation_config["initial_temperature"],
        "Contact resistance [Ohm]": simulation_config["contact_resistance"],
        "Upper voltage cut-off [V]": simulation_config["upper_voltage_cutoff"],
        "Lower voltage cut-off [V]": simulation_config["lower_voltage_cutoff"],
    }

    default_params.update(pybamm_params, check_already_exists=False)

    # Model options
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    # Capacity calibration (simplified - 3 iterations for speed)
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

    # Quick calibration (3 iterations max for canvas performance)
    for iteration in range(3):
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=default_params,
        )

        sol_capacity = sim_capacity.solve(
            solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
        )

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah

        if 0.999 < scale_factor < 1.001:
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

    # Run drive cycle simulation
    time_s = np.array(drive_cycle["time_s"])
    values = -np.array(drive_cycle["power_W"])
    drive_data = np.column_stack((time_s, values))

    period = simulation_config.get("period", "1 second")

    # Get custom termination thresholds from config
    anode_threshold = simulation_config.get("anode_potential_threshold_V")
    temp_threshold = simulation_config.get("jelly_roll_temperature_threshold_K")
    lower_voltage = simulation_config["lower_voltage_cutoff"]

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
            pybamm.step.CustomTermination(
                "Jelly roll temperature cut-off [K]", temperature_cutoff
            )
        )

    # Add voltage cutoff as custom termination (string format doesn't work with InputParameter)
    def voltage_cutoff(variables):
        return variables["Terminal voltage [V]"] - lower_voltage

    termination_conditions.append(
        pybamm.step.CustomTermination("Voltage cut-off [V]", voltage_cutoff)
    )

    # Build experiment with custom terminations
    drive_cycle_step_with_term = pybamm.step.power(
        drive_data,
        duration=time_s[-1],
        termination=termination_conditions,
    )
    experiment = pybamm.Experiment([drive_cycle_step_with_term], period=period)

    model = pybamm.lithium_ion.SPMe(options=model_options)
    model.variables["Anode potential [V]"] = model.variables[
        "Negative electrode surface potential difference at separator interface [V]"
    ]

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

    solution = sim.solve(initial_soc=initial_soc, solver=solver)
    termination_reason = getattr(solution, "termination", "completed")

    # Extract results
    timeseries = {
        "time_s": solution["Time [s]"].entries.tolist(),
        "voltage_V": solution["Terminal voltage [V]"].entries.tolist(),
        "current_A": solution["Current [A]"].entries.tolist(),
        "temperature_K": solution[
            "Volume-averaged cell temperature [K]"
        ].entries.tolist(),
        "capacity_Ah": solution["Discharge capacity [A.h]"].entries.tolist(),
        "energy_Wh": solution["Discharge energy [W.h]"].entries.tolist(),
        "power_W": solution["Power [W]"].entries.tolist(),
    }

    # Calculate summary
    sim_time = solution["Time [s]"].entries
    sim_voltage = solution["Terminal voltage [V]"].entries
    sim_current = solution["Current [A]"].entries
    sim_power = solution["Power [W]"].entries
    sim_temp = solution["Volume-averaged cell temperature [K]"].entries
    sim_capacity = solution["Discharge capacity [A.h]"].entries

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
    }

    # Energy analysis
    dt = np.diff(sim_time)
    power_mid = (sim_power[:-1] + sim_power[1:]) / 2
    discharge_mask = power_mid > 0

    energy_discharged = float(
        np.sum(power_mid[discharge_mask] * dt[discharge_mask]) / 3600
    )
    capacity_used = float(sim_capacity[-1] - sim_capacity[0])

    energy_analysis = {
        "energy_discharged_Wh": energy_discharged,
        "capacity_used_Ah": capacity_used,
        "soc_change_pct": capacity_used / nominal_capacity * 100,
    }

    # Range analysis
    min_soc = simulation_config.get("min_soc", 0.10)
    max_soc = simulation_config.get("max_soc", 0.90)
    available_capacity = nominal_capacity * (initial_soc - min_soc)

    cycles_possible = available_capacity / capacity_used if capacity_used > 0 else 0
    flight_time_s = cycles_possible * (sim_time[-1] - sim_time[0])

    range_analysis = {
        "initial_soc": initial_soc,
        "min_soc": min_soc,
        "available_capacity_Ah": available_capacity,
        "capacity_per_cycle_Ah": capacity_used,
        "energy_per_cycle_Wh": energy_discharged,
        "cycles_possible": cycles_possible,
        "flight_time_min": flight_time_s / 60,
        "flight_time_hr": flight_time_s / 3600,
    }

    # Add pack info
    range_analysis["pack_config"] = {
        "cells_in_series": int(cells_series),
        "cells_in_parallel": int(cells_parallel),
        "pack_capacity_Ah": nominal_capacity * cells_parallel,
        "pack_energy_Wh": nominal_energy * cells_series * cells_parallel,
    }

    return {
        "success": True,
        "termination_reason": termination_reason,
        "timeseries": timeseries,
        "summary": summary,
        "energy_analysis": energy_analysis,
        "range_analysis": range_analysis,
    }


# Process all designs
results_by_design = {}

for design_id, d in cell_design_data.items():
    # Build cell_design dict from input component data
    cell_design = {
        "nominal_capacity": {"value": d["kpis.nominal_capacity.value"]},
        "nominal_energy": {"value": d["kpis.nominal_energy.value"]},
        "nominal_voltage": {"value": d["kpis.nominal_voltage.value"]},
        "upper_voltage_cutoff": {"value": d["cell_design.upper_voltage_cutoff.value"]},
        "lower_voltage_cutoff": {"value": d["cell_design.lower_voltage_cutoff.value"]},
        "cell_volume": {"value": d["kpis.cell_volume.value"]},
        "positive_electrode": {
            "count": {"value": d["cell_design.positive_electrode.count.value"]},
            "height": {"value": d["cell_design.positive_electrode.height.value"]},
            "width": {"value": d["cell_design.positive_electrode.width.value"]},
            "coating": {
                "thickness": {
                    "value": d["cell_design.positive_electrode.coating.thickness.value"]
                },
                "porosity": {
                    "value": d["cell_design.positive_electrode.coating.porosity.value"]
                },
                "density": {
                    "value": d["cell_design.positive_electrode.coating.density.value"]
                },
                "active_material_volume_fraction": {
                    "value": d[
                        "cell_design.positive_electrode.coating.active_material_volume_fraction.value"
                    ]
                },
                "formulation": {
                    "primary_active_material": {
                        "name": d[
                            "cell_design.positive_electrode.coating.formulation.primary_active_material.name"
                        ]
                    }
                },
            },
            "foil": {
                "thickness": {
                    "value": d["cell_design.positive_electrode.foil.thickness.value"]
                },
                "material": {
                    "density": {
                        "value": d[
                            "cell_design.positive_electrode.foil.material.density.value"
                        ]
                    },
                    "electrical_conductivity": {
                        "value": d[
                            "cell_design.positive_electrode.foil.material.electrical_conductivity.value"
                        ]
                    },
                },
            },
        },
        "negative_electrode": {
            "height": {"value": d["cell_design.negative_electrode.height.value"]},
            "width": {"value": d["cell_design.negative_electrode.width.value"]},
            "coating": {
                "thickness": {
                    "value": d["cell_design.negative_electrode.coating.thickness.value"]
                },
                "porosity": {
                    "value": d["cell_design.negative_electrode.coating.porosity.value"]
                },
                "density": {
                    "value": d["cell_design.negative_electrode.coating.density.value"]
                },
                "active_material_volume_fraction": {
                    "value": d[
                        "cell_design.negative_electrode.coating.active_material_volume_fraction.value"
                    ]
                },
            },
            "foil": {
                "thickness": {
                    "value": d["cell_design.negative_electrode.foil.thickness.value"]
                },
                "material": {
                    "density": {
                        "value": d[
                            "cell_design.negative_electrode.foil.material.density.value"
                        ]
                    },
                    "electrical_conductivity": {
                        "value": d[
                            "cell_design.negative_electrode.foil.material.electrical_conductivity.value"
                        ]
                    },
                },
            },
        },
        "separator": {
            "thickness": {"value": d["cell_design.separator.thickness.value"]},
            "porosity": {"value": d["cell_design.separator.porosity.value"]},
            "material": {
                "physical_properties": {
                    "density": {
                        "value": d["cell_design.separator.material.density.value"]
                    }
                }
            },
        },
        "jelly_roll": {"count": {"value": d["cell_design.jelly_roll.count.value"]}},
    }

    # Build simulation_config
    simulation_config = {
        "ambient_temperature": ambient_temp,
        "initial_temperature": initial_temp,
        "initial_soc": initial_soc,
        "upper_voltage_cutoff": d["cell_design.upper_voltage_cutoff.value"],
        "lower_voltage_cutoff": d["cell_design.lower_voltage_cutoff.value"],
        "contact_resistance": contact_resistance,
        "total_heat_transfer_coefficient": heat_transfer_coeff,
        "cooling_surface_area": cooling_area,
        "period": "1 second",
        "min_soc": min_soc,
        "max_soc": max_soc,
        "pack_nominal_voltage_V": pack_nominal_voltage_V,
        "pack_energy_kWh": pack_energy_kWh,
        "pack_peak_power_kW": pack_peak_power_kW,
        "drive_cycle": {
            "time_s": drive_cycle_data["time_s"],
            "power_W": drive_cycle_data["power_W"],
            "label": "Drone Flight Profile",
        },
    }

    # Run the simulation for this design
    design_result = run_drive_cycle(cell_design, simulation_config)
    results_by_design[design_id] = design_result

result = results_by_design
