"""
SPMeT (Single Particle Model with electrolyte and Thermal) Module

Unified PyBaMM model that takes experiment strings via simulation config
and returns raw time series data for post-processing.
"""

import numpy as np
import pybamm
import json
from pathlib import Path


def _create_exchange_current_density_function(m_ref: float, E_r: float = 17800):
    """
    Create an exchange-current density function for Butler-Volmer kinetics.

    Args:
        m_ref: Reference exchange-current density coefficient [(A/m2)(m3/mol)^1.5]
        E_r: Activation energy [J/mol] (default: 17800)

    Returns:
        Function that computes exchange-current density as f(c_e, c_s_surf, c_s_max, T)
    """

    def exchange_current_density(c_e, c_s_surf, c_s_max, T):
        """
        Exchange-current density for Butler-Volmer reactions.

        Parameters:
            c_e: Electrolyte concentration [mol.m-3]
            c_s_surf: Particle surface concentration [mol.m-3]
            c_s_max: Maximum particle concentration [mol.m-3]
            T: Temperature [K]

        Returns:
            Exchange-current density [A.m-2]
        """
        arrhenius = np.exp(E_r / pybamm.constants.R * (1 / 298.15 - 1 / T))
        return (
            m_ref * arrhenius * c_e**0.5 * c_s_surf**0.5 * (c_s_max - c_s_surf) ** 0.5
        )

    return exchange_current_density


class dict2obj:
    """Simple class for dot notation access to nested dicts."""

    def __init__(self, d):
        for key, value in d.items():
            if isinstance(value, dict):
                setattr(self, key, dict2obj(value))
            else:
                setattr(self, key, value)

    def get(self, key, default=None):
        val = getattr(self, key, default)
        if val is default and not isinstance(default, dict2obj):
            return default
        return val


def run_spmet(
    cell_design_manifest: dict,
    simulation_config: dict | None = None,
) -> list[dict]:
    """
    Run SPMeT simulation with specified experiment configuration.

    This function handles:
    1. Model parameter setup from cell design manifest
    2. Capacity calibration via electrode width adjustment
    3. Running the specified experiment(s)
    4. Returning raw time series data

    Args:
        cell_design_manifest: Cell design parameters dictionary

        simulation_config: Simulation configuration dictionary containing:
            - temperature_K: Temperature [K] (default: 298.15)
            - initial_soc: Initial state of charge [0-1] (default: 1.0)
            - experiments: List of PyBaMM experiment strings to run
            - experiment_labels: List of labels for each experiment (optional)
            - period: Sampling period string (default: "1 second")
            - lower_voltage_cutoff: Lower voltage cutoff [V] (default: 2.5)
            - upper_voltage_cutoff: Upper voltage cutoff [V] (default: 3.65)
            - contact_resistance: Contact resistance [Ohm] (default: 1e-5)

    Returns:
        List of dictionaries, one per experiment, each containing:
            - time_s: Array of time points [s]
            - voltage_V: Array of terminal voltages [V]
            - current_A: Array of currents [A]
            - temperature_K: Array of cell temperatures [K]
            - capacity_Ah: Array of discharge capacity [Ah]
            - energy_Wh: Array of discharge energy [Wh]
            - power_W: Array of power [W]
            - experiment_label: Label for this experiment
            - success: Boolean indicating if simulation succeeded
            - error: Error message if failed (optional)
            - config: Configuration used

    Example:
        >>> config = {
        ...     "initial_soc": 1.0,
        ...     "experiments": [
        ...         "Discharge at 0.5C for 2 hours or until 2.5 V",
        ...         "Discharge at 1C for 1 hour or until 2.5 V",
        ...     ],
        ...     "experiment_labels": ["0.5C", "1C"],
        ... }
        >>> results = run_spmet(cell_design_manifest, config)
        >>> for r in results:
        ...     print(f"{r['experiment_label']}: {len(r['time_s'])} points")
    """
    if simulation_config is None:
        raise ValueError("simulation_config must be provided")

    # Convert old-style config (c_rate, duration_s, direction) to new experiments format
    if "experiments" not in simulation_config and "c_rate" in simulation_config:
        c_rate = simulation_config.get("c_rate", 1.0)
        duration_s = simulation_config.get("duration_s", 30)
        direction = simulation_config.get("direction", "discharge")

        # Don't include voltage cutoff - let the simulation run for the specified duration
        # Voltage cutoffs with high C-rates can cause "infeasible" errors due to IR drop
        if direction == "discharge":
            exp_str = f"Discharge at {c_rate}C for {duration_s} seconds"
        else:
            exp_str = f"Charge at {c_rate}C for {duration_s} seconds"

        simulation_config = {
            **simulation_config,
            "experiments": [exp_str],
            "experiment_labels": [f"{c_rate}C_{direction}"],
            "period": "0.1 second",
        }

    # Build PyBaMM parameters from manifest
    default_params = _build_parameters(cell_design_manifest, simulation_config)

    # Get cell design parameters
    cell_design = dict2obj(cell_design_manifest["cell_design"])
    kpis = dict2obj(cell_design_manifest["kpis"])

    # Set PyBaMM model options
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    # Capacity calibration
    target_capacity_Ah = kpis.nominal_capacity.value
    default_params = _calibrate_capacity(
        default_params, model_options, cell_design, target_capacity_Ah
    )

    # Get experiments from config
    experiments = simulation_config.get("experiments")
    experiment_labels = simulation_config.get("experiment_labels")

    if not experiments:
        raise ValueError("No experiments provided in simulation_config['experiments']")

    # Pad labels if needed
    while len(experiment_labels) < len(experiments):
        experiment_labels.append(f"exp_{len(experiment_labels)}")

    print("\n" + "=" * 80)
    print("RUNNING EXPERIMENTS")
    print("=" * 80)

    initial_soc = simulation_config.get("initial_soc")
    period = simulation_config.get("period")

    all_results = []

    for exp_str, label in zip(experiments, experiment_labels):
        print(f"\nRunning: {label}")
        print(f"  Experiment: {exp_str[:60]}{'...' if len(exp_str) > 60 else ''}")

        result = _run_experiment(
            default_params,
            model_options,
            exp_str,
            initial_soc,
            period,
            label,
            simulation_config,
        )
        all_results.append(result)

    print("\n" + "=" * 80)
    print(
        f"Completed {len([r for r in all_results if r['success']])}/{len(all_results)} experiments"
    )
    print("=" * 80)

    return all_results


# Helper functions
def _build_parameters(
    cell_design_manifest: dict, simulation_config: dict
) -> pybamm.ParameterValues:
    """Build PyBaMM parameters from cell design manifest."""
    default_params = pybamm.ParameterValues({})

    cell_design = dict2obj(cell_design_manifest["cell_design"])
    kpis = dict2obj(cell_design_manifest["kpis"])

    optimized = (
        cell_design_manifest.get("simulation_models")
        .get("SPMeT")
        .get("optimized_parameters")
    )

    print("\nBuilding model parameters from manifest...")

    # Load OCP data from material files
    materials_dir = Path(__file__).parent.parent.parent / "materials"

    pos_electrode = cell_design.positive_electrode
    neg_electrode = cell_design.negative_electrode

    pos_material_name = pos_electrode.coating.formulation.primary_active_material.name
    neg_material_name = neg_electrode.coating.formulation.primary_active_material.name

    pos_material_path = materials_dir / f"{pos_material_name}.json"
    neg_material_path = materials_dir / f"{neg_material_name}.json"

    # Load material data
    with open(pos_material_path, "r") as f:
        pos_material = dict2obj(json.load(f))
    with open(neg_material_path, "r") as f:
        neg_material = dict2obj(json.load(f))

    # Positive electrode OCP
    pos_ocp, sto_p_0, sto_p_100 = _load_ocp_data(pos_material_path, "positive")

    # Negative electrode OCP
    neg_ocp, sto_n_0, sto_n_100 = _load_ocp_data(neg_material_path, "negative")

    # Debug: print stoichiometry values
    print(f"  Positive electrode: sto_0={sto_p_0:.4f}, sto_100={sto_p_100:.4f}")
    print(f"  Negative electrode: sto_0={sto_n_0:.4f}, sto_100={sto_n_100:.4f}")

    # Calculate expected OCV at both SOC extremes
    pos_ocp_data = pos_ocp[1]  # (stoich, volts) tuple
    neg_ocp_data = neg_ocp[1]
    pos_v_0 = np.interp(sto_p_0, pos_ocp_data[0], pos_ocp_data[1])
    neg_v_0 = np.interp(sto_n_0, neg_ocp_data[0], neg_ocp_data[1])
    pos_v_100 = np.interp(sto_p_100, pos_ocp_data[0], pos_ocp_data[1])
    neg_v_100 = np.interp(sto_n_100, neg_ocp_data[0], neg_ocp_data[1])
    print(
        f"  OCV at 0% cell SOC: {pos_v_0:.3f} - {neg_v_0:.3f} = {pos_v_0 - neg_v_0:.3f} V"
    )
    print(
        f"  OCV at 100% cell SOC: {pos_v_100:.3f} - {neg_v_100:.3f} = {pos_v_100 - neg_v_100:.3f} V"
    )

    # Cell parameters
    cell_params = {
        "Open-circuit voltage at 0% SOC [V]": optimized.get(
            "Open-circuit voltage at 0% SOC [V]",
            cell_design.lower_voltage_cutoff.value,
        ),
        "Open-circuit voltage at 100% SOC [V]": optimized.get(
            "Open-circuit voltage at 100% SOC [V]",
            cell_design.upper_voltage_cutoff.value,
        ),
        "Nominal cell capacity [A.h]": kpis.nominal_capacity.value,
        "Number of cells connected in series to make a battery": 1.0,
    }

    # Positive electrode parameters
    number_of_coated_sides = 2
    pos_electrode = cell_design.positive_electrode

    positive_electrode_params = {
        "Number of electrodes connected in parallel to make a cell": (
            pos_electrode.count.value
            * cell_design.jelly_roll.count.value
            * number_of_coated_sides
        ),
        "Electrode height [m]": pos_electrode.height.value / 1000,
        "Electrode width [m]": pos_electrode.width.value / 1000,
        "Electrode length [m]": pos_electrode.width.value / 1000,
        "Positive electrode thickness [m]": pos_electrode.coating.thickness.value / 1e6,
        "Positive electrode porosity": pos_electrode.coating.porosity.value,
        "Positive electrode active material volume fraction": pos_electrode.coating.active_material_volume_fraction.value,
        "Positive electrode density [kg.m-3]": pos_electrode.coating.density.value
        * 1000,
        "Positive electrode specific heat capacity [J.kg-1.K-1]": pos_material.thermal_properties.specific_heat_capacity.value,
        "Positive electrode conductivity [S.m-1]": pos_material.physical_properties.conductivity.value,
        "Positive particle diffusivity [m2.s-1]": pos_material.electrochemical_properties.diffusion_coefficient.value,
        "Positive electrode Bruggeman coefficient (electrode)": pos_electrode.coating.bruggeman_coefficient.value,
        "Positive electrode Bruggeman coefficient (electrolyte)": pos_electrode.coating.bruggeman_coefficient.value,
        "Positive electrode OCP [V]": pos_ocp,
        "Positive electrode OCP entropic change [V.K-1]": pos_material.thermal_properties.ocp_entropic_change.value,
        "Positive electrode charge transfer coefficient": pos_material.electrochemical_properties.charge_transfer_coefficient.value,
        "Positive electrode double-layer capacity [F.m-2]": pos_material.electrochemical_properties.double_layer_capacitance.value,
        "Positive electrode exchange-current density [A.m-2]": _create_exchange_current_density_function(
            pos_material.electrochemical_properties.reaction_rate.value
        ),
        "Positive particle radius [m]": pos_material.physical_properties.particle_size.d50.value
        / 1e6,
        "Maximum stoichiometry in positive electrode": sto_p_0,
        "Minimum stoichiometry in positive electrode": sto_p_100,
        "Maximum concentration in positive electrode [mol.m-3]": pos_material.electrochemical_properties.max_lithium_concentration.value,
        # Initial at 50% SOC (midpoint between sto_p_0 and sto_p_100)
        "Initial concentration in positive electrode [mol.m-3]": (sto_p_0 + sto_p_100)
        / 2
        * pos_material.electrochemical_properties.max_lithium_concentration.value,
    }

    positive_cc_params = {
        "Positive current collector thickness [m]": pos_electrode.foil.thickness.value
        / 1e6,
        "Positive current collector conductivity [S.m-1]": pos_electrode.foil.material.electrical_conductivity.value,
        "Positive current collector density [kg.m-3]": pos_electrode.foil.material.density.value
        * 1000,
        "Positive current collector thermal conductivity [W.m-1.K-1]": pos_electrode.foil.material.thermal_conductivity.value,
        "Positive current collector specific heat capacity [J.kg-1.K-1]": pos_electrode.foil.material.specific_heat.value,
    }

    # Negative electrode parameters
    neg_electrode = cell_design.negative_electrode

    negative_electrode_params = {
        "Negative electrode porosity": neg_electrode.coating.porosity.value,
        "Negative electrode active material volume fraction": neg_electrode.coating.active_material_volume_fraction.value,
        "Negative electrode density [kg.m-3]": neg_electrode.coating.density.value
        * 1000,
        "Negative electrode specific heat capacity [J.kg-1.K-1]": neg_material.thermal_properties.specific_heat_capacity.value,
        "Negative electrode conductivity [S.m-1]": neg_material.physical_properties.conductivity.value,
        "Negative particle diffusivity [m2.s-1]": neg_material.electrochemical_properties.diffusion_coefficient.value,
        "Negative electrode Bruggeman coefficient (electrode)": neg_electrode.coating.bruggeman_coefficient.value,
        "Negative electrode Bruggeman coefficient (electrolyte)": neg_electrode.coating.bruggeman_coefficient.value,
        "Negative electrode OCP [V]": neg_ocp,
        "Negative electrode OCP entropic change [V.K-1]": neg_material.thermal_properties.ocp_entropic_change.value,
        "Negative electrode charge transfer coefficient": neg_material.electrochemical_properties.charge_transfer_coefficient.value,
        "Negative electrode double-layer capacity [F.m-2]": neg_material.electrochemical_properties.double_layer_capacitance.value,
        "Negative electrode exchange-current density [A.m-2]": _create_exchange_current_density_function(
            neg_material.electrochemical_properties.reaction_rate.value
        ),
        "Negative electrode thickness [m]": neg_electrode.coating.thickness.value / 1e6,
        "Negative particle radius [m]": neg_material.physical_properties.particle_size.d50.value
        / 1e6,
        "Maximum stoichiometry in negative electrode": sto_n_100,
        "Minimum stoichiometry in negative electrode": sto_n_0,
        "Maximum concentration in negative electrode [mol.m-3]": neg_material.electrochemical_properties.max_lithium_concentration.value,
        # Initial at 50% SOC (midpoint between sto_n_0 and sto_n_100)
        "Initial concentration in negative electrode [mol.m-3]": (sto_n_0 + sto_n_100)
        / 2
        * neg_material.electrochemical_properties.max_lithium_concentration.value,
    }

    negative_cc_params = {
        "Negative current collector thickness [m]": neg_electrode.foil.thickness.value
        / 1e6,
        "Negative current collector conductivity [S.m-1]": neg_electrode.foil.material.electrical_conductivity.value,
        "Negative current collector density [kg.m-3]": neg_electrode.foil.material.density.value
        * 1000,
        "Negative current collector thermal conductivity [W.m-1.K-1]": neg_electrode.foil.material.thermal_conductivity.value,
        "Negative current collector specific heat capacity [J.kg-1.K-1]": neg_electrode.foil.material.specific_heat.value,
    }

    # Separator parameters
    separator_material_name = cell_design.separator.name
    separator_material_path = materials_dir / f"{separator_material_name}.json"
    with open(separator_material_path, "r") as f:
        separator_material = dict2obj(json.load(f))

    separator_params = {
        "Separator thickness [m]": cell_design.separator.thickness.value / 1e6,
        "Separator porosity": cell_design.separator.porosity.value,
        "Separator density [kg.m-3]": cell_design.separator.material.density.value
        * 1000,
        "Separator specific heat capacity [J.kg-1.K-1]": separator_material.thermal_properties.specific_heat_capacity.value,
        "Separator Bruggeman coefficient (electrolyte)": separator_material.thermal_properties.bruggeman_coefficient.value,
        "Separator thermal conductivity [W.m-1.K-1]": separator_material.thermal_properties.thermal_conductivity.value,
    }

    # Electrolyte parameters
    electrolyte_name = cell_design.electrolyte.name
    electrolyte_path = (
        Path(__file__).parent.parent.parent / "materials" / f"{electrolyte_name}.json"
    )
    with open(electrolyte_path, "r") as f:
        electrolyte = dict2obj(json.load(f))

    electrolyte_params = {
        "Cation transference number": electrolyte.transference_number.reference_value.value,
        "Electrolyte conductivity [S.m-1]": electrolyte.ionic_conductivity.reference_value.value
        * 0.1,
        "Electrolyte diffusivity [m2.s-1]": electrolyte.ionic_diffusivity.reference_value.value
        * 1e-4,
        "Initial concentration in electrolyte [mol.m-3]": cell_design.electrolyte.concentration.value
        * 1000,
        "Thermodynamic factor": electrolyte.thermodynamic_factor.reference_value.value,
    }

    # Thermal parameters
    thermal_params = {
        "Reference temperature [K]": 298.15,
        "Total heat transfer coefficient [W.m-2.K-1]": simulation_config[
            "total_heat_transfer_coefficient"
        ],
        "Cell cooling surface area [m2]": simulation_config["cooling_surface_area"],
        "Cell volume [m3]": kpis.cell_volume.value / 1000.0,
    }

    # Operating conditions
    operating_conditions = {
        "Ambient temperature [K]": simulation_config["ambient_temperature"],
        "Initial temperature [K]": simulation_config["initial_temperature"],
        "Contact resistance [Ohm]": simulation_config["contact_resistance"],
        "Upper voltage cut-off [V]": simulation_config["upper_voltage_cutoff"],
        "Lower voltage cut-off [V]": simulation_config["lower_voltage_cutoff"],
        "Current function [A]": kpis.nominal_capacity.value,  # 1C current
    }

    # Combine all parameters
    pybamm_params = {
        **cell_params,
        **positive_electrode_params,
        **positive_cc_params,
        **negative_electrode_params,
        **negative_cc_params,
        **separator_params,
        **electrolyte_params,
        **thermal_params,
        **operating_conditions,
    }

    default_params.update(pybamm_params, check_already_exists=False)
    print("  Parameters loaded")

    return default_params


def _load_ocp_data(file_path: Path, electrode_type: str) -> tuple:
    """Load OCP data from JSON file."""
    if not file_path.exists():
        raise FileNotFoundError(f"Material file not found: {file_path}")

    with open(file_path, "r") as f:
        data = json.load(f)

    ocv_data = data["electrochemical_properties"]["ocv"]["data"]

    if isinstance(ocv_data["stoichiometry"], dict):
        stoich_raw = ocv_data["stoichiometry"]["value"]
        volts_raw = ocv_data["average"]["value"]
    else:
        stoich_raw = ocv_data["stoichiometry"]
        volts_raw = ocv_data["average"]

    stoich = np.array(stoich_raw, dtype=np.float64).flatten()
    volts = np.array(volts_raw, dtype=np.float64).flatten()

    # Sort and deduplicate
    sort_idx = np.argsort(stoich)
    stoich = stoich[sort_idx]
    volts = volts[sort_idx]
    _, unique_idx = np.unique(stoich, return_index=True)
    stoich = stoich[unique_idx]
    volts = volts[unique_idx]

    ocp_name = (
        "Positive_OCP_data" if electrode_type == "positive" else "Negative_OCP_data"
    )
    ocp = (ocp_name, (stoich, volts))

    # Return (ocp, sto_at_0%_cell_SOC, sto_at_100%_cell_SOC)
    # At 100% cell SOC: cathode is delithiated (low sto), anode is lithiated (high sto)
    # At 0% cell SOC: cathode is lithiated (high sto), anode is delithiated (low sto)
    if electrode_type == "positive":
        # Cathode: low stoichiometry at 100% cell SOC, high at 0% cell SOC
        return ocp, stoich.max(), stoich.min()
    else:
        # Anode: high stoichiometry at 100% cell SOC, low at 0% cell SOC
        return ocp, stoich.min(), stoich.max()


def _calibrate_capacity(
    default_params: pybamm.ParameterValues,
    model_options: dict,
    cell_design,
    target_capacity_Ah: float,
) -> pybamm.ParameterValues:
    """Calibrate electrode width to match target capacity."""
    print("\n" + "=" * 80)
    print("CAPACITY CALIBRATION")
    print("=" * 80)
    print(f"Target capacity: {target_capacity_Ah:.2f} Ah")
    I_0_33C = target_capacity_Ah / 3
    I_0_1C = target_capacity_Ah / 10
    print(
        f"Charge current: {I_0_33C:.2f} A (C/3), Discharge current: {I_0_1C:.2f} A (C/10)"
    )
    print(
        f"Upper voltage: {cell_design.upper_voltage_cutoff.value} V, Lower voltage: {cell_design.lower_voltage_cutoff.value} V"
    )
    print(
        f"Nominal capacity in params: {default_params['Nominal cell capacity [A.h]']:.2f} Ah"
    )
    print(
        f"Pos sto limits: min={default_params['Minimum stoichiometry in positive electrode']:.4f}, max={default_params['Maximum stoichiometry in positive electrode']:.4f}"
    )
    print(
        f"Neg sto limits: min={default_params['Minimum stoichiometry in negative electrode']:.4f}, max={default_params['Maximum stoichiometry in negative electrode']:.4f}"
    )

    # Check what PyBaMM calculates as the cell capacity
    model_check = pybamm.lithium_ion.SPMe(options=model_options)
    sim_check = pybamm.Simulation(model_check, parameter_values=default_params)
    sim_check.build()
    Q_calc = sim_check.parameter_values.evaluate(model_check.param.Q)
    print(f"PyBaMM calculated cell capacity: {Q_calc:.2f} Ah")

    # Use C-rate syntax which PyBaMM handles better
    charge_step = f"Charge at 0.1C until {cell_design.upper_voltage_cutoff.value} V"
    hold_step = (
        f"Hold at {cell_design.upper_voltage_cutoff.value} V for 2 hours or until C/50"
    )
    discharge_step = f"Discharge at 0.1C for 15 hours or until {cell_design.lower_voltage_cutoff.value} V"

    print(f"Experiment steps:")
    print(f"  1. Rest, {charge_step}, {hold_step}")
    print(f"  2. Rest")
    print(f"  3. {discharge_step}")
    print(f"  4. Rest")

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

    print(f"Convergence tolerance: {TOLERANCE*100:.3f}%")
    print("-" * 80)

    for iteration in range(MAX_ITERATIONS):
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=default_params,
        )

        try:
            # Don't use initial_soc - let PyBaMM use the initial concentrations we set
            sol_capacity = sim_capacity.solve(
                solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
            )
        except pybamm.SolverError as e:
            print(f"Capacity calibration failed: {e}")
            raise

        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            print(f"Warning: Insufficient cycles: {len(sol_capacity.cycles)}")
            # Print cycles termination conditions
            for i in range(len(sol_capacity.cycles)):
                print(f"Cycle {i+1}: {sol_capacity.cycles[i]['Current [A]'].entries}")
                print(
                    f"Cycle {i+1}: {sol_capacity.cycles[i]['Terminal voltage [V]'].entries}"
                )
                print(f"Cycle {i+1}: {sol_capacity.cycles[i].termination}")
            break

        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        scale_factor = discharge_capacity / target_capacity_Ah
        error_percent = abs(1 - scale_factor) * 100

        print(
            f"Iteration {iteration+1:2d}: Capacity = {discharge_capacity:6.2f} Ah, Error = {error_percent:6.3f}%"
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

    print(f"Final electrode width: {default_params['Electrode width [m]']*1000:.2f} mm")
    print(f"Final capacity: {default_params['Nominal cell capacity [A.h]']:.2f} Ah")
    print("Final OCV limits:")
    print(
        f"  OCV at 100% SOC: {default_params['Open-circuit voltage at 100% SOC [V]']:.2f} V"
    )
    print(
        f"  OCV at 0% SOC: {default_params['Open-circuit voltage at 0% SOC [V]']:.2f} V"
    )

    return default_params


def _run_experiment(
    default_params: pybamm.ParameterValues,
    model_options: dict,
    experiment_str: str,
    initial_soc: float,
    period: str,
    experiment_label: str,
    simulation_config: dict,
) -> dict:
    """Run a single experiment and return time series data."""
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
        ],
    )

    # Build PyBaMM experiment from string
    experiment = pybamm.Experiment(
        [
            ("Rest for 1 seconds"),
            (experiment_str,),
        ],
        period=period,
    )

    model = pybamm.lithium_ion.SPMe(options=model_options)
    sim = pybamm.Simulation(
        model, parameter_values=default_params, experiment=experiment, var_pts=var_pts
    )

    try:
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        # Extract data from the main cycle (cycle index 1)
        if hasattr(solution, "cycles") and len(solution.cycles) > 1:
            cycle = solution.cycles[1]
        else:
            cycle = solution

        result = {
            "time_s": cycle["Time [s]"].entries,
            "voltage_V": cycle["Terminal voltage [V]"].entries,
            "current_A": cycle["Current [A]"].entries,
            "temperature_K": cycle["Volume-averaged cell temperature [K]"].entries,
            "capacity_Ah": cycle["Discharge capacity [A.h]"].entries,
            "energy_Wh": cycle["Discharge energy [W.h]"].entries,
            "power_W": cycle["Power [W]"].entries,
            "experiment_label": experiment_label,
            "success": True,
            "config": simulation_config,
        }

        print(f"  Completed: {len(result['time_s'])} data points")
        return result

    except pybamm.SolverError as e:
        print(f"  Failed: {str(e)[:60]}")
        return {
            "time_s": np.array([]),
            "voltage_V": np.array([]),
            "current_A": np.array([]),
            "temperature_K": np.array([]),
            "capacity_Ah": np.array([]),
            "energy_Wh": np.array([]),
            "power_W": np.array([]),
            "experiment_label": experiment_label,
            "success": False,
            "error": str(e),
            "config": simulation_config,
        }
