"""
SPMeT Drive Cycle Simulation - Battery Electric Vehicle (BEV)
"""

import pybamm
import numpy as np

# Get all inputs from upstream components
cell_design_data = componentInputs.get("Detailed Cell Design Data", {})

# Get drive cycle data - support multiple cycles
cycles = {}
cycle_inputs = {
    "WLTP": componentInputs.get("WLTP Drive Cycle Data", {}),
    "Nurburgring": componentInputs.get("Nurburgring Drive Cycle Data", {}),
    "US06": componentInputs.get("US06 Drive Cycle Data", {}),
}

# Known cycle distances
cycle_distances = {
    "WLTP": 23.266,
    "Nurburgring": 20.8,
    "US06": 12.8,
}

# Only add cycles that have data
for cycle_name, cycle_data in cycle_inputs.items():
    if cycle_data and "time_s" in cycle_data and "power_W" in cycle_data:
        cycles[cycle_name] = {
            "data": cycle_data,
            "distance_km": cycle_distances.get(cycle_name),
        }

# Get simulation parameters
ambient_temp = componentInputs.get("Ambient Temperature (K)")
initial_temp = componentInputs.get("Initial Temperature (K)")
initial_soc = componentInputs.get("Initial SOC")
contact_resistance = componentInputs.get("Contact Resistance (Ohm)")
heat_transfer_coeff = componentInputs.get("Heat Transfer Coefficient (W.m-2.K-1)")
cooling_area = componentInputs.get("Cooling Surface Area (m2)")
min_soc = componentInputs.get("Min SOC")
max_soc = componentInputs.get("Max SOC")

# Pack configuration
pack_energy_kWh = componentInputs.get("Pack Max Energy (kWh)")
pack_nominal_voltage_V = componentInputs.get("Pack Nominal Voltage (V)")
pack_peak_power_kW = componentInputs.get("Pack Peak Power (kW)")

# Vehicle parameters
vehicle_weight_kg = componentInputs.get("Vehicle Weight (kg)")
vehicle_drag_coeff = componentInputs.get("Vehicle Drag Coefficient")
vehicle_frontal_area_m2 = componentInputs.get("Vehicle Frontal Area (m2)")
vehicle_rolling_resistance = componentInputs.get("Vehicle Rolling Resistance")
vehicle_drivetrain_eff = componentInputs.get("Vehicle Drivetrain Efficiency")


def run_drive_cycle(cell_design, simulation_config):
    """Run BEV drive cycle simulation."""
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

    cathode_material = cell_design["positive_electrode"]["coating"]["formulation"][
        "primary_active_material"
    ]["name"]

    if "LFP" in cathode_material.upper():
        default_params = pybamm.ParameterValues("Prada2013")
    else:
        default_params = pybamm.ParameterValues("ORegan2022")

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
        "Separator density [kg.m-3]": separator["material"]["density"]["value"] * 1000,
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

    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    # Capacity calibration - simplified to 1 iteration for canvas
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

    # Single calibration iteration
    sim_capacity = pybamm.Simulation(
        model_capacity,
        experiment=capacity_match_experiment,
        parameter_values=default_params,
    )

    sol_capacity = sim_capacity.solve(solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3))

    discharge_cycle = sol_capacity.cycles[2]
    discharge_capacity = float(
        discharge_cycle["Discharge capacity [A.h]"].entries[-1]
        - discharge_cycle["Discharge capacity [A.h]"].entries[0]
    )

    scale_factor = discharge_capacity / target_capacity_Ah
    new_width = default_params["Electrode width [m]"] / scale_factor
    default_params.update(
        {
            "Electrode width [m]": new_width,
            "Nominal cell capacity [A.h]": discharge_capacity / scale_factor,
        },
        check_already_exists=False,
    )

    # Run drive cycle
    time_s = np.array(drive_cycle["time_s"])
    values = -np.array(drive_cycle["power_W"])
    drive_data = np.column_stack((time_s, values))

    period = simulation_config["period"]
    lower_voltage = simulation_config["lower_voltage_cutoff"]

    def voltage_cutoff(variables):
        return variables["Terminal voltage [V]"] - lower_voltage

    termination_conditions = [
        pybamm.step.CustomTermination("Voltage cut-off [V]", voltage_cutoff)
    ]

    drive_cycle_step = pybamm.step.power(
        drive_data, duration=time_s[-1], termination=termination_conditions
    )
    experiment = pybamm.Experiment([drive_cycle_step], period=period)

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
        model, parameter_values=default_params, experiment=experiment, var_pts=var_pts
    )

    initial_soc_val = simulation_config["initial_soc"]

    solution = sim.solve(initial_soc=initial_soc_val, solver=solver)
    termination_reason = getattr(solution, "termination", "completed")

    result_data = {
        "success": True,
        "termination_reason": termination_reason,
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

    sim_time = np.array(result_data["time_s"])
    sim_voltage = np.array(result_data["voltage_V"])
    sim_current = np.array(result_data["current_A"])
    sim_power = np.array(result_data["power_W"])
    sim_temp = np.array(result_data["temperature_K"])
    sim_capacity_Ah = np.array(result_data["capacity_Ah"])

    summary = {
        "duration_s": float(sim_time[-1] - sim_time[0]),
        "voltage_min_V": float(sim_voltage.min()),
        "voltage_max_V": float(sim_voltage.max()),
        "temperature_min_C": float(sim_temp.min() - 273.15),
        "temperature_max_C": float(sim_temp.max() - 273.15),
        "temperature_rise_C": float(sim_temp.max() - sim_temp[0]),
    }

    dt = np.diff(sim_time)
    power_mid = (sim_power[:-1] + sim_power[1:]) / 2
    discharge_mask = power_mid > 0
    regen_mask = power_mid < 0

    energy_discharged = float(
        np.sum(power_mid[discharge_mask] * dt[discharge_mask]) / 3600
    )
    energy_regen = float(np.sum(power_mid[regen_mask] * dt[regen_mask]) / 3600)
    energy_net = energy_discharged + energy_regen
    capacity_used = float(sim_capacity_Ah[-1] - sim_capacity_Ah[0])

    energy_analysis = {
        "energy_discharged_Wh": energy_discharged,
        "energy_regenerated_Wh": abs(energy_regen),
        "energy_net_Wh": energy_net,
        "capacity_used_Ah": capacity_used,
        "soc_change_pct": capacity_used / nominal_capacity * 100,
    }

    # Physics-based speed and distance estimation
    weight_kg = simulation_config["vehicle_weight_kg"]
    Cd = simulation_config["vehicle_drag_coefficient"]
    A = simulation_config["vehicle_frontal_area_m2"]
    eta = simulation_config["vehicle_drivetrain_efficiency"]
    Crr = simulation_config["vehicle_rolling_resistance"]
    rho = 1.225  # Air density kg/m3

    g = 9.81
    W = weight_kg * g

    # Use pack-level power and its matching time base for speed/distance calculation
    drive_time_s = np.array(drive_cycle["time_s"])
    power_for_vehicle = pack_power_W
    speed_ms = np.zeros_like(power_for_vehicle)

    drag_coef = 0.5 * rho * Cd * A
    F_roll = Crr * W

    for i, P_mech in enumerate(power_for_vehicle):
        P_out = abs(P_mech) * eta

        if P_out < 1e-3:
            speed_ms[i] = 0.0
            continue

        # Ground vehicle: P = (drag_coef * v^2 + Crr * W) * v
        # Cubic equation: drag_coef * v^3 + Crr * W * v - P = 0
        coeffs = [drag_coef, 0, F_roll, -P_out]
        roots = np.roots(coeffs)
        real_positive_roots = [r.real for r in roots if np.isreal(r) and r.real > 0]

        if len(real_positive_roots) > 0:
            speed_ms[i] = float(real_positive_roots[0])

    avg_speed_kmh = (
        float(np.mean(speed_ms[speed_ms > 0]) * 3.6) if np.any(speed_ms > 0) else 0.0
    )
    max_speed_kmh = float(np.max(speed_ms) * 3.6)

    # Calculate physics-based distance using drive cycle time base
    drive_dt = np.diff(drive_time_s)
    speed_mid = (speed_ms[:-1] + speed_ms[1:]) / 2
    distance_m = float(np.sum(speed_mid * drive_dt))
    physics_distance_km = distance_m / 1000

    # Use provided cycle distance or fall back to physics calculation
    cycle_distance_km = drive_cycle.get("distance_km")
    if cycle_distance_km is None:
        cycle_distance_km = physics_distance_km

    min_soc_val = simulation_config["min_soc"]
    max_soc_val = simulation_config["max_soc"]
    available_capacity = nominal_capacity * (initial_soc_val - min_soc_val)
    cycles_possible = available_capacity / capacity_used if capacity_used > 0 else 0

    range_analysis = {
        "cycle_label": drive_cycle["label"],
        "cycle_distance_km": cycle_distance_km,
        "physics_distance_km": physics_distance_km,
        "avg_speed_kmh": avg_speed_kmh,
        "max_speed_kmh": max_speed_kmh,
        "capacity_per_cycle_Ah": capacity_used,
        "energy_per_cycle_Wh": energy_net,
        "cycles_possible": cycles_possible,
    }

    if cycle_distance_km and cycle_distance_km > 0:
        range_analysis["range_km"] = cycles_possible * cycle_distance_km
        range_analysis["energy_per_km_Wh"] = energy_net / cycle_distance_km

    return {
        "success": True,
        "termination_reason": termination_reason,
        "timeseries": result_data,
        "summary": summary,
        "energy_analysis": energy_analysis,
        "range_analysis": range_analysis,
    }


# Process first design only for canvas performance
results_by_design = {}

# Pick first design
for design_id, d in list(cell_design_data.items()):
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
                "density": {"value": d["cell_design.separator.material.density.value"]}
            },
        },
        "jelly_roll": {"count": {"value": d["cell_design.jelly_roll.count.value"]}},
    }

    # Run simulation for each drive cycle
    design_results = {}

    for cycle_name, cycle_data in cycles.items():
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
            "vehicle_weight_kg": vehicle_weight_kg,
            "vehicle_drag_coefficient": vehicle_drag_coeff,
            "vehicle_frontal_area_m2": vehicle_frontal_area_m2,
            "vehicle_rolling_resistance": vehicle_rolling_resistance,
            "vehicle_drivetrain_efficiency": vehicle_drivetrain_eff,
            "drive_cycle": {
                "time_s": cycle_data["data"]["time_s"],
                "power_W": cycle_data["data"]["power_W"],
                "label": cycle_name,
                "distance_km": cycle_data["distance_km"],
            },
        }

        cycle_result = run_drive_cycle(cell_design, simulation_config)
        design_results[cycle_name] = cycle_result

    results_by_design[design_id] = design_results

result = results_by_design
