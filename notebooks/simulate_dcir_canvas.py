"""
DCIR Surface Sweep Calculation

Standalone DCIR simulation using PyBaMM SPMe model.
"""

import pybamm
import numpy as np

# Get parameters from upstream components
soc_levels = componentInputs.get("SoC Levels", [0.1, 0.3, 0.5, 0.7, 0.9])
temps_C = componentInputs.get("Temperatures (C)", [0, 15, 30, 45])
c_rates = componentInputs.get("C-Rates", [0.1, 1.0, 10.0, 30.0])
contact_resistance = componentInputs.get("Contact Resistance", 1e-5)

# Get cell design input to extract design_id
cell_design_input = componentInputs.get("Cell Design Input", {})
design_id = list(cell_design_input.keys())[0] if cell_design_input else None

if not design_id:
    result = {
        "success": False,
        "error": "No cell design found in input component",
        "surface_data": [],
        "sweep_params": {
            "soc_values": soc_levels,
            "temperature_C_values": temps_C,
            "temperature_K_values": [t + 273.15 for t in temps_C],
            "c_rate_values": c_rates,
        },
    }
else:

    def simulate_dcir(
        cell_design,
        kpis,
        initial_soc=0.5,
        temperature_K=298.15,
        c_rate=1.0,
        contact_resistance=1e-5,
    ):
        """
        Simulate DCIR at specific time points (0.1s, 1s, 10s, 18s, 30s).
        """
        if cell_design is None:
            return {"success": False, "error": "cell_design is None"}

        if kpis is None:
            return {"success": False, "error": "kpis is None"}

        nominal_capacity = kpis.get("nominal_capacity", {}).get("value")

        if nominal_capacity is None:
            return {
                "success": False,
                "error": "Nominal capacity not found in kpis",
            }

        # Convert inputs to arrays
        soc_array = np.atleast_1d(initial_soc)
        temp_array = np.atleast_1d(temperature_K)
        crate_array = np.atleast_1d(c_rate)

        # Check if this is a sweep (any input has more than one value)
        is_sweep = len(soc_array) > 1 or len(temp_array) > 1 or len(crate_array) > 1

        if is_sweep:
            return _run_dcir_sweep(
                cell_design=cell_design,
                kpis=kpis,
                soc_array=soc_array,
                temp_array=temp_array,
                crate_array=crate_array,
                contact_resistance=contact_resistance,
            )

        # Single point simulation - continue with original logic
        initial_soc = float(soc_array[0])
        temperature_K = float(temp_array[0])
        c_rate = float(crate_array[0])

        # Build PyBaMM parameters from cell design
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
            "Nominal cell capacity [A.h]": nominal_capacity,
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
            "Positive electrode porosity": pos_electrode["coating"]["porosity"][
                "value"
            ],
            "Positive electrode active material volume fraction": pos_electrode[
                "coating"
            ]["active_material_volume_fraction"]["value"],
            "Positive electrode density [kg.m-3]": pos_electrode["coating"]["density"][
                "value"
            ]
            * 1000,
        }

        positive_cc_params = {
            "Positive current collector thickness [m]": pos_electrode["foil"][
                "thickness"
            ]["value"]
            / 1e6,
        }

        # Negative electrode parameters
        neg_electrode = cell_design["negative_electrode"]

        negative_electrode_params = {
            "Negative electrode thickness [m]": neg_electrode["coating"]["thickness"][
                "value"
            ]
            / 1e6,
            "Negative electrode porosity": neg_electrode["coating"]["porosity"][
                "value"
            ],
            "Negative electrode active material volume fraction": neg_electrode[
                "coating"
            ]["active_material_volume_fraction"]["value"],
            "Negative electrode density [kg.m-3]": neg_electrode["coating"]["density"][
                "value"
            ]
            * 1000,
        }

        negative_cc_params = {
            "Negative current collector thickness [m]": neg_electrode["foil"][
                "thickness"
            ]["value"]
            / 1e6,
        }

        # Separator parameters
        separator = cell_design["separator"]
        separator_params = {
            "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
            "Separator porosity": separator["porosity"]["value"],
            "Separator density [kg.m-3]": 1000,
            "Separator specific heat capacity [J.kg-1.K-1]": 700,
        }

        # Thermal parameters
        thermal_params = {
            "Reference temperature [K]": 298.15,
            "Total heat transfer coefficient [W.m-2.K-1]": 0.01,
            "Cell cooling surface area [m2]": 0.1,
            "Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
        }

        # Get voltage cutoffs from cell design
        upper_voltage = cell_design.get("upper_voltage_cutoff", {}).get("value", 4.2)
        lower_voltage = cell_design.get("lower_voltage_cutoff", {}).get("value", 2.5)

        # Operating conditions
        operating_conditions = {
            "Ambient temperature [K]": temperature_K,
            "Initial temperature [K]": temperature_K,
            "Contact resistance [Ohm]": contact_resistance,
            "Upper voltage cut-off [V]": upper_voltage,
            "Lower voltage cut-off [V]": lower_voltage,
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

        # Capacity calibration
        target_capacity_Ah = nominal_capacity

        charge_step = f"Charge at 0.1C until {upper_voltage} V"
        hold_step = f"Hold at {upper_voltage} V for 2 hours or until C/50"
        discharge_step = f"Discharge at 0.1C for 15 hours or until {lower_voltage} V"

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

            if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
                ocv_100 = float(
                    sol_capacity.cycles[1]["Terminal voltage [V]"].entries[-1]
                )
                ocv_0 = float(
                    sol_capacity.cycles[3]["Terminal voltage [V]"].entries[-1]
                )

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

        # Run DCIR pulse simulation
        pulse_duration = 30.0
        exp_str = f"Discharge at {c_rate}C for {pulse_duration} seconds"

        experiment = pybamm.Experiment(
            [
                ("Rest for 1 seconds",),
                (exp_str,),
            ],
            period="0.01 second",
        )

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

        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        # Extract pulse cycle data
        if hasattr(solution, "cycles") and len(solution.cycles) > 1:
            data_source = solution.cycles[1]
        else:
            data_source = solution

        time_s = data_source["Time [s]"].entries
        voltage_V = data_source["Terminal voltage [V]"].entries

        # Calculate DCIR at requested time points
        v_rest = voltage_V[0]
        i_amplitude = nominal_capacity * c_rate

        requested_points = [0.1, 1.0, 10.0, 18.0, 30.0]
        dcir_mOhm = {}

        for t_point in requested_points:
            # Find index closest to the requested time point relative to start
            t_idx = np.argmin(np.abs(time_s - time_s[0] - t_point))
            v_pulse = voltage_V[t_idx]

            # DCIR [Ohm] = (V_rest - V_pulse) / I + R_contact
            dcir_ohm = (v_rest - v_pulse) / i_amplitude + contact_resistance
            dcir_mOhm[str(t_point)] = float(dcir_ohm * 1000)

        return {
            "success": True,
            "dcir_mOhm": dcir_mOhm,
            "conditions": {
                "initial_soc": initial_soc,
                "temperature_K": temperature_K,
                "temperature_C": temperature_K - 273.15,
                "c_rate": c_rate,
                "contact_resistance_Ohm": contact_resistance,
            },
        }

    def _run_dcir_sweep(
        cell_design,
        kpis,
        soc_array,
        temp_array,
        crate_array,
        contact_resistance=1e-5,
    ):
        """
        Run DCIR sweep across multiple SOC, temperature, and C-rate values.
        """
        # Ensure inputs are numpy arrays
        soc_array = np.asarray(soc_array)
        temp_array = np.asarray(temp_array)
        crate_array = np.asarray(crate_array)

        nominal_capacity = kpis.get("nominal_capacity", {}).get("value")

        # Build PyBaMM parameters from cell design (done once)
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
            "Nominal cell capacity [A.h]": nominal_capacity,
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
            "Positive electrode porosity": pos_electrode["coating"]["porosity"][
                "value"
            ],
            "Positive electrode active material volume fraction": pos_electrode[
                "coating"
            ]["active_material_volume_fraction"]["value"],
            "Positive electrode density [kg.m-3]": pos_electrode["coating"]["density"][
                "value"
            ]
            * 1000,
        }

        positive_cc_params = {
            "Positive current collector thickness [m]": pos_electrode["foil"][
                "thickness"
            ]["value"]
            / 1e6,
        }

        # Negative electrode parameters
        neg_electrode = cell_design["negative_electrode"]

        negative_electrode_params = {
            "Negative electrode thickness [m]": neg_electrode["coating"]["thickness"][
                "value"
            ]
            / 1e6,
            "Negative electrode porosity": neg_electrode["coating"]["porosity"][
                "value"
            ],
            "Negative electrode active material volume fraction": neg_electrode[
                "coating"
            ]["active_material_volume_fraction"]["value"],
            "Negative electrode density [kg.m-3]": neg_electrode["coating"]["density"][
                "value"
            ]
            * 1000,
        }

        negative_cc_params = {
            "Negative current collector thickness [m]": neg_electrode["foil"][
                "thickness"
            ]["value"]
            / 1e6,
        }

        # Separator parameters
        separator = cell_design["separator"]
        separator_params = {
            "Separator thickness [m]": separator["thickness"]["value"] / 1e6,
            "Separator porosity": separator["porosity"]["value"],
            "Separator density [kg.m-3]": 1000,
            "Separator specific heat capacity [J.kg-1.K-1]": 700,
        }

        # Get voltage cutoffs from cell design
        upper_voltage = cell_design.get("upper_voltage_cutoff", {}).get("value", 4.2)
        lower_voltage = cell_design.get("lower_voltage_cutoff", {}).get("value", 2.5)

        # Thermal parameters (will be updated per temperature)
        thermal_params = {
            "Reference temperature [K]": 298.15,
            "Total heat transfer coefficient [W.m-2.K-1]": 0.01,
            "Cell cooling surface area [m2]": 0.1,
            "Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
        }

        # Combine base parameters
        base_params = {
            **cell_params,
            **positive_electrode_params,
            **positive_cc_params,
            **negative_electrode_params,
            **negative_cc_params,
            **separator_params,
            **thermal_params,
        }

        default_params.update(base_params, check_already_exists=False)

        # Set PyBaMM model options
        model_options = {
            "calculate discharge energy": "true",
            "cell geometry": "arbitrary",
            "thermal": "lumped",
            "contact resistance": "true",
        }

        # Capacity calibration (done once at reference temperature)
        ref_temp = 298.15
        target_capacity_Ah = nominal_capacity

        # Set reference temperature for calibration
        default_params.update(
            {
                "Ambient temperature [K]": ref_temp,
                "Initial temperature [K]": ref_temp,
                "Contact resistance [Ohm]": contact_resistance,
                "Upper voltage cut-off [V]": upper_voltage,
                "Lower voltage cut-off [V]": lower_voltage,
            },
            check_already_exists=False,
        )

        charge_step = f"Charge at 0.1C until {upper_voltage} V"
        hold_step = f"Hold at {upper_voltage} V for 2 hours or until C/50"
        discharge_step = f"Discharge at 0.1C for 15 hours or until {lower_voltage} V"

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

            if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
                ocv_100 = float(
                    sol_capacity.cycles[1]["Terminal voltage [V]"].entries[-1]
                )
                ocv_0 = float(
                    sol_capacity.cycles[3]["Terminal voltage [V]"].entries[-1]
                )

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

        # Now run DCIR sweep
        surface_data = []
        sim_count = 0
        requested_points = [0.1, 1.0, 10.0, 18.0, 30.0]
        pulse_duration = 30.0

        for temp_K in temp_array:
            temp_C = temp_K - 273.15

            # Update temperature in parameters
            default_params.update(
                {
                    "Ambient temperature [K]": float(temp_K),
                    "Initial temperature [K]": float(temp_K),
                },
                check_already_exists=False,
            )

            for soc in soc_array:
                for c_rate in crate_array:
                    sim_count += 1

                    # Build experiment for this C-rate
                    exp_str = f"Discharge at {c_rate}C for {pulse_duration} seconds"
                    experiment = pybamm.Experiment(
                        [("Rest for 1 seconds",), (exp_str,)],
                        period="0.1 second",
                    )

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
                        ],
                    )

                    sim = pybamm.Simulation(
                        model,
                        parameter_values=default_params,
                        experiment=experiment,
                        var_pts=var_pts,
                    )

                    solution = sim.solve(initial_soc=float(soc), solver=solver)

                    # Extract pulse cycle data
                    if hasattr(solution, "cycles") and len(solution.cycles) > 1:
                        data_source = solution.cycles[1]
                    else:
                        data_source = solution

                    time_s = data_source["Time [s]"].entries
                    voltage_V = data_source["Terminal voltage [V]"].entries

                    # Calculate DCIR at requested time points
                    v_rest = voltage_V[0]
                    i_amplitude = nominal_capacity * c_rate

                    dcir_mOhm = {}
                    for t_point in requested_points:
                        t_idx = np.argmin(np.abs(time_s - time_s[0] - t_point))
                        actual_time = time_s[t_idx] - time_s[0]

                        if actual_time >= t_point * 0.9:
                            v_pulse = voltage_V[t_idx]
                            dcir_ohm = (
                                v_rest - v_pulse
                            ) / i_amplitude + contact_resistance
                            dcir_mOhm[str(t_point)] = float(dcir_ohm * 1000)
                        else:
                            dcir_mOhm[str(t_point)] = np.nan

                    surface_data.append(
                        {
                            "soc": float(soc),
                            "soc_pct": float(soc * 100),
                            "temperature_K": float(temp_K),
                            "temperature_C": float(temp_C),
                            "c_rate": float(c_rate),
                            "dcir_mOhm": dcir_mOhm,
                            "success": True,
                        }
                    )

        return {
            "success": True,
            "surface_data": surface_data,
            "sweep_params": {
                "soc_values": soc_array.tolist(),
                "temperature_K_values": temp_array.tolist(),
                "temperature_C_values": (temp_array - 273.15).tolist(),
                "c_rate_values": crate_array.tolist(),
            },
            "num_simulations": sim_count,
            "dcir_time_points_s": requested_points,
        }

    # Extract cell design and kpis from input
    d = cell_design_input[design_id]

    # Validate that we have the required data
    if not d:
        result = {
            "success": False,
            "error": "Cell design data is empty",
        }
    elif d.get("kpis.nominal_capacity.value") is None:
        result = {
            "success": False,
            "error": "Nominal capacity not found in cell design data",
        }
    else:
        # Validate critical values that will be multiplied
        critical_keys = [
            "cell_design.positive_electrode.coating.density.value",
            "cell_design.negative_electrode.coating.density.value",
            "kpis.cell_volume.value",
            "cell_design.positive_electrode.count.value",
            "cell_design.jelly_roll.count.value",
        ]

        missing_keys = [key for key in critical_keys if d.get(key) is None]

        if missing_keys:
            result = {
                "success": False,
                "error": f"Missing required cell design values: {', '.join(missing_keys)}",
            }
        else:
            # Build cell_design dict from input component data
            cell_design = {
                "nominal_capacity": {"value": d.get("kpis.nominal_capacity.value")},
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
                    },
                },
                "separator": {
                    "thickness": {
                        "value": d.get("cell_design.separator.thickness.value")
                    },
                    "porosity": {
                        "value": d.get("cell_design.separator.porosity.value")
                    },
                    "material": {"density": {"value": 700}},
                },
                "jelly_roll": {
                    "count": {"value": d.get("cell_design.jelly_roll.count.value")}
                },
            }

            kpis = {
                "nominal_capacity": {"value": d.get("kpis.nominal_capacity.value")},
            }

            # Convert temperatures to Kelvin
            temps_K = [t + 273.15 for t in temps_C]

            # Run DCIR sweep
            dcir_results = simulate_dcir(
                cell_design=cell_design,
                kpis=kpis,
                initial_soc=soc_levels,
                temperature_K=temps_K,
                c_rate=c_rates,
                contact_resistance=contact_resistance,
            )

            result = dcir_results
