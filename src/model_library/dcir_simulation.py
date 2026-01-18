"""
DCIR (DC Internal Resistance) Simulation Module

Simulates DCIR using PyBaMM with cell design parameters and operating conditions.
"""

import numpy as np
import pybamm
import json
from pathlib import Path


# Simple class for dot notation access to nested dicts
class dict2obj:
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


def simulate_dcir(
    cell_design_manifest: dict,
    simulation_config: dict | None = None,
) -> dict:
    """
    Simulate DC internal resistance using PyBaMM.

    Args:
        cell_design_manifest: Cell design parameters dictionary containing:

        config: Simulation configuration dictionary containing:
            - temperature_C: Temperature [°C] (default: 25)
            - initial_soc: Initial state of charge [0-1] (default: 0.5)
            - c_rate: C-rate for discharge pulse (default: 1.0)
            - pulse_duration_s: Pulse duration [s] (default: 30)
            - time_points_s: Time points for DCIR extraction [s]
            - contact_resistance_ohm: Contact resistance [Ω] (default: 1e-5)

    Returns:
        Dictionary containing:
            - time_s: Array of time points [s]
            - dcir_mohm: Array of DCIR values [mΩ]
            - voltage_V: Array of voltages during pulse [V]
            - v_rest_V: Rest voltage before pulse [V]
            - current_A: Pulse current [A]
            - dcir_df: DataFrame with detailed results
            - config: Configuration used
            - cell_params: Cell parameters used

    Example:
        >>> cell_params = {
        ...     "nominal_capacity_Ah": 135.0,
        ...     "electrode_height_m": 0.200,
        ...     "electrode_width_m": 0.150,
        ...     "lower_voltage_cutoff_V": 2.5,
        ...     "upper_voltage_cutoff_V": 3.65,
        ... }
        >>> config = {"temperature_C": 25, "initial_soc": 0.5, "c_rate": 1.0}
        >>> results = simulate_dcir(cell_params, config)
        >>> print(f"10s DCIR: {results['dcir_df'].loc[results['dcir_df']['time_s'] == 10, 'dcir_mohm'].values[0]:.2f} mΩ")
    """
    # Ensure simulation_config is a dict
    if simulation_config is None:
        simulation_config = {}

    # Create PyBaMM parameter set
    # Start with empty ParameterValues to build from scratch
    default_params = pybamm.ParameterValues({})

    # Extract cell design with dot notation support
    cell_design = dict2obj(cell_design_manifest["cell_design"])
    kpis = dict2obj(cell_design_manifest["kpis"])

    # Try to get optimized parameters for better baseline
    optimized = (
        cell_design_manifest.get("simulation_models", {})
        .get("SPMeT", {})
        .get("optimized_parameters", {})
    )

    print("\nStep 1: Updating cell parameters from manifest")

    # ============================================================================
    # MATERIAL LOADING (from JSON files)
    # ============================================================================
    # Load LFP cathode parameters

    # Use absolute paths for material files
    materials_dir = Path("/Users/manik/Github/model_library/materials")
    lfp_path = materials_dir / "LFP_Generic_v1.json"
    graphite_path = materials_dir / "Graphite_Generic_v1.json"

    # LFP OCP Function
    if lfp_path.exists():
        with open(lfp_path, "r") as f:
            lfp_data = json.load(f)
        lfp_ocv_data = lfp_data["electrochemical_properties"]["ocv"]["data"]
        # Handle nesting in LFP JSON (stoichiometry/average may have 'value' key)
        if isinstance(lfp_ocv_data["stoichiometry"], dict):
            lfp_stoich_raw = lfp_ocv_data["stoichiometry"]["value"]
            lfp_volts_raw = lfp_ocv_data["average"]["value"]
        else:
            lfp_stoich_raw = lfp_ocv_data["stoichiometry"]
            lfp_volts_raw = lfp_ocv_data["average"]

        _lfp_stoich = np.array(lfp_stoich_raw, dtype=np.float64).flatten()
        _lfp_volts = np.array(lfp_volts_raw, dtype=np.float64).flatten()

        # Sort for monotonicity
        sort_idx = np.argsort(_lfp_stoich)
        _lfp_stoich = _lfp_stoich[sort_idx]
        _lfp_volts = _lfp_volts[sort_idx]

        # Deduplicate
        _, unique_idx = np.unique(_lfp_stoich, return_index=True)
        _lfp_stoich = _lfp_stoich[unique_idx]
        _lfp_volts = _lfp_volts[unique_idx]

        # Create OCP using PyBaMM's tuple format (name, (x, y)) for data-driven OCP
        # This is the standard way to pass tabulated OCP data to PyBaMM
        lfp_ocp = ("LFP_OCP_data", (_lfp_stoich, _lfp_volts))

        # Define stoichiometry windows for LFP
        sto_p_0 = 0.001
        sto_p_100 = 0.98
    else:
        # Fallback to default if JSON missing
        lfp_ocp = default_params["Positive electrode OCP [V]"]
        sto_p_0 = 0.001
        sto_p_100 = 0.98

    # Graphite OCP Function
    if graphite_path.exists():
        with open(graphite_path, "r") as f:
            graphite_data = json.load(f)
        graphite_ocv_data = graphite_data["electrochemical_properties"]["ocv"]["data"]
        # Handle nesting in Graphite JSON
        if isinstance(graphite_ocv_data["stoichiometry"], dict):
            g_stoich_raw = graphite_ocv_data["stoichiometry"]["value"]
            g_volts_raw = graphite_ocv_data["average"]["value"]
        else:
            g_stoich_raw = graphite_ocv_data["stoichiometry"]
            g_volts_raw = graphite_ocv_data["average"]

        _graphite_stoich = np.array(g_stoich_raw, dtype=np.float64).flatten()
        _graphite_volts = np.array(g_volts_raw, dtype=np.float64).flatten()

        # Sort for monotonicity
        sort_idx = np.argsort(_graphite_stoich)
        _graphite_stoich = _graphite_stoich[sort_idx]
        _graphite_volts = _graphite_volts[sort_idx]

        # Deduplicate
        _, unique_idx = np.unique(_graphite_stoich, return_index=True)
        _graphite_stoich = _graphite_stoich[unique_idx]
        _graphite_volts = _graphite_volts[unique_idx]

        # Create OCP using PyBaMM's tuple format (name, (x, y)) for data-driven OCP
        # This is the standard way to pass tabulated OCP data to PyBaMM
        graphite_ocp = ("Graphite_OCP_data", (_graphite_stoich, _graphite_volts))

        # Define stoichiometry windows for Graphite
        sto_n_0 = 0.98
        sto_n_100 = 0.10
    else:
        # Fallback to default if JSON missing
        graphite_ocp = default_params["Negative electrode OCP [V]"]
        sto_n_0 = 0.98
        sto_n_100 = 0.10

    # ============================================================================
    # CELL PARAMETERS
    # ============================================================================
    cell_params = {
        "Open-circuit voltage at 0% SOC [V]": optimized.get(
            "Open-circuit voltage at 0% SOC [V]",
            getattr(
                cell_design, "lower_voltage_cutoff", dict2obj({"value": 2.5})
            ).value,
        ),
        "Open-circuit voltage at 100% SOC [V]": optimized.get(
            "Open-circuit voltage at 100% SOC [V]",
            getattr(
                cell_design, "upper_voltage_cutoff", dict2obj({"value": 3.65})
            ).value,
        ),
        "Nominal cell capacity [A.h]": kpis.get(
            "nominal_capacity", dict2obj({"value": 135.0})
        ).value,
        "Number of cells connected in series to make a battery": 1.0,
    }

    # ============================================================================
    # POSITIVE ELECTRODE PARAMETERS
    # ============================================================================
    number_of_coated_sides = 2
    pos_electrode = cell_design.positive_electrode

    # Helper to get nested value from formulation
    def get_formulation_val(electrode, path_parts, default=None):
        curr = getattr(electrode, "coating", None)
        if not curr:
            return default
        curr = getattr(curr, "formulation", None)
        if not curr:
            return default
        for part in path_parts:
            curr = getattr(curr, part, None)
            if not curr:
                return default
        return getattr(curr, "value", default) if hasattr(curr, "value") else curr

    pos_conductivity = get_formulation_val(
        pos_electrode,
        ["primary_active_material", "material", "electrical_conductivity"],
        10.0,
    )

    positive_electrode_params = {
        "Number of electrodes connected in parallel to make a cell": pos_electrode.count.value
        * cell_design.jelly_roll.count.value
        * number_of_coated_sides,
        "Electrode height [m]": pos_electrode.height.value / 1000,
        "Electrode width [m]": pos_electrode.width.value / 1000,
        "Electrode length [m]": pos_electrode.width.value
        / 1000,  # Use width as length if not specified
        "Positive electrode thickness [m]": pos_electrode.coating.thickness.value / 1e6,
        "Positive electrode porosity": pos_electrode.coating.porosity.value,
        "Positive electrode active material volume fraction": pos_electrode.coating.active_material_volume_fraction.value,
        "Positive electrode density [kg.m-3]": pos_electrode.coating.density.value
        * 1000,
        "Positive electrode specific heat capacity [J.kg-1.K-1]": 700.0,
        "Positive electrode conductivity [S.m-1]": pos_conductivity,
        "Positive particle diffusivity [m2.s-1]": 1e-15,  # Default if missing
        "Positive electrode Bruggeman coefficient (electrode)": 1.5,
        "Positive electrode Bruggeman coefficient (electrolyte)": 1.5,
        "Positive electrode OCP [V]": lfp_ocp,
        "Positive electrode OCP entropic change [V.K-1]": 0,
        "Positive electrode charge transfer coefficient": 0.5,
        "Positive electrode double-layer capacity [F.m-2]": 0.2,
        "Positive electrode exchange-current density [A.m-2]": 0.1,
        "Positive particle radius [m]": 5e-08,
        "Initial stoichiometry in positive electrode": sto_p_100,
        "Maximum stoichiometry in positive electrode": sto_p_100,
        "Minimum stoichiometry in positive electrode": sto_p_0,
        "Maximum concentration in positive electrode [mol.m-3]": 22806.0,
        # Initial concentration as a function (required for initial_soc)
        "Initial concentration in positive electrode [mol.m-3]": sto_p_100 * 22806.0,
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

    # ============================================================================
    # NEGATIVE ELECTRODE PARAMETERS
    # ============================================================================
    neg_electrode = cell_design.negative_electrode
    neg_conductivity = get_formulation_val(
        neg_electrode,
        ["primary_active_material", "material", "electrical_conductivity"],
        100.0,
    )

    negative_electrode_params = {
        "Negative electrode porosity": neg_electrode.coating.porosity.value,
        "Negative electrode active material volume fraction": neg_electrode.coating.active_material_volume_fraction.value,
        "Negative electrode density [kg.m-3]": neg_electrode.coating.density.value
        * 1000,
        "Negative electrode specific heat capacity [J.kg-1.K-1]": 700.0,
        "Negative electrode conductivity [S.m-1]": neg_conductivity,
        "Negative particle diffusivity [m2.s-1]": 3e-15,  # Default if missing
        "Negative electrode Bruggeman coefficient (electrode)": 1.5,
        "Negative electrode Bruggeman coefficient (electrolyte)": 1.5,
        "Negative electrode OCP [V]": graphite_ocp,
        "Negative electrode OCP entropic change [V.K-1]": 0,
        "Negative electrode charge transfer coefficient": 0.5,
        "Negative electrode double-layer capacity [F.m-2]": 0.2,
        "Negative electrode exchange-current density [A.m-2]": 0.1,
        "Negative electrode thickness [m]": neg_electrode.coating.thickness.value / 1e6,
        "Negative particle radius [m]": 5e-06,
        "Initial stoichiometry in negative electrode": sto_n_100,
        "Maximum stoichiometry in negative electrode": sto_n_0,
        "Minimum stoichiometry in negative electrode": sto_n_100,
        "Maximum concentration in negative electrode [mol.m-3]": 30555,
        # Initial concentration as a function (required for initial_soc)
        "Initial concentration in negative electrode [mol.m-3]": sto_n_100 * 30555,
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

    # ============================================================================
    # SEPARATOR PARAMETERS
    # ============================================================================
    separator_params = {
        "Separator thickness [m]": cell_design.separator.thickness.value
        / 1e6,  # um to m
        "Separator porosity": cell_design.separator.porosity.value,
        "Separator density [kg.m-3]": cell_design.separator.material.density.value
        * 1000,  # g/cm³ to kg/m³
        "Separator specific heat capacity [J.kg-1.K-1]": 1978.0,  # Typical PE separator value
        "Separator Bruggeman coefficient (electrolyte)": 1.5,  # Default Bruggeman coefficient
        "Separator thermal conductivity [W.m-1.K-1]": 0.16,  # Typical PE separator value
    }

    # ============================================================================
    # ELECTROLYTE PARAMETERS
    # ============================================================================
    electrolyte_name = cell_design.electrolyte.name
    # Add electrolyte parameters based on electrolyte name by loading the json file
    # Load electrolyte parameters from json file in materials folder use Pathlib
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

    # ============================================================================
    # THERMAL PARAMETERS
    # ============================================================================
    thermal_params = {
        "Reference temperature [K]": 298.15,
        "Total heat transfer coefficient [W.m-2.K-1]": simulation_config.get(
            "total_heat_transfer_coefficient", 10.0
        ),
        "Cell cooling surface area [m2]": cell_design.cell_cooling_surface_area.value
        / 1e6,  # m²
        "Cell volume [m3]": kpis.cell_volume.value / 1000.0,  # m³
    }

    # ============================================================================
    # OPERATING CONDITIONS
    # ============================================================================
    # Contact resistance constant (10 μΩ = 1e-5 Ω)
    operating_conditions = {
        "Ambient temperature [K]": simulation_config.get("temperature_K", 298.15),
        "Initial temperature [K]": simulation_config.get("temperature_K", 298.15),
        "Contact resistance [Ohm]": simulation_config.get("contact_resistance", 1e-5),
        "Current function [A]": simulation_config.get("c_rate", 1.0)
        * kpis.nominal_capacity.value,
        "Upper voltage cut-off [V]": simulation_config.get(
            "upper_voltage_cutoff", 3.65
        ),
        "Lower voltage cut-off [V]": simulation_config.get("lower_voltage_cutoff", 2.5),
    }

    # Target capacity from manifest
    target_capacity_Ah = kpis.nominal_capacity.value

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

    # Update parameters
    default_params.update(pybamm_params, check_already_exists=False)

    print("  ✓ Design parameters updated")
    print("  ✓ Positive electrode parameters updated")
    print("  ✓ Negative electrode parameters updated")
    print("  ✓ Separator parameters updated")
    print("  ✓ Thermal parameters updated")
    print("  ✓ Operating conditions updated")

    # Setup SPMe model options for all simulations
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
    }

    print(
        "\nStep 3: Capacity matching - Calibrating electrode width to match BYD 135Ah capacity"
    )
    print("=" * 80)

    # Setup capacity matching experiment
    # Use conservative C-rates and voltage limits for calibration
    capacity_match_experiment = pybamm.Experiment(
        [
            (
                "Rest for 1 seconds",
                f"Charge at 0.1C for 36000 seconds or until {cell_design.upper_voltage_cutoff.value} V",
                f"Hold at {cell_design.upper_voltage_cutoff.value} V until 0.02C",
            ),
            ("Rest for 3600 seconds",),
            (
                f"Discharge at 0.1C for 360000 seconds or until {cell_design.lower_voltage_cutoff.value} V"
            ),
            ("Rest for 3600 seconds",),
        ],
        period="1 second",
    )

    # Create SPMe model for capacity matching
    model_capacity = pybamm.lithium_ion.SPMe(options=model_options)

    # Iterative capacity matching (similar to update_model_parameters in base.py)
    MAX_ITERATIONS = 20
    TOLERANCE = 0.0001  # 0.01% tolerance

    print(f"Target capacity: {target_capacity_Ah} Ah")
    print(f"Maximum iterations: {MAX_ITERATIONS}")
    print(f"Convergence tolerance: {TOLERANCE*100:.3f}%")
    print(f"\nStarting iterative capacity matching...")
    print("-" * 80)

    for iteration in range(MAX_ITERATIONS):
        sim_capacity = pybamm.Simulation(
            model_capacity,
            experiment=capacity_match_experiment,
            parameter_values=default_params,
        )

        # Solve at 80% SOC for stable calibration
        try:
            sol_capacity = sim_capacity.solve(
                initial_soc=0.8, solver=pybamm.IDAKLUSolver(atol=1e-3, rtol=1e-3)
            )
        except pybamm.SolverError as e:
            print(f"Capacity calibration simulation failed: {e}")
            print("This may be due to:")
            print("  - Voltage cutoff reached before pulse completed")
            print("  - Temperature limit exceeded")
            print("  - Electrode parameters causing numerical instability")
            raise

        # Check we have enough cycles
        if not hasattr(sol_capacity, "cycles") or len(sol_capacity.cycles) < 4:
            print(
                f"⚠️  Warning: Insufficient cycles (got {len(sol_capacity.cycles) if hasattr(sol_capacity, 'cycles') else 0})"
            )
            break

        # Extract discharge capacity from cycle 2 (first full discharge after charge)
        discharge_cycle = sol_capacity.cycles[2]
        discharge_capacity = float(
            discharge_cycle["Discharge capacity [A.h]"].entries[-1]
            - discharge_cycle["Discharge capacity [A.h]"].entries[0]
        )

        # Calculate scaling factor
        scale_factor = discharge_capacity / target_capacity_Ah

        # Calculate error
        error_percent = abs(1 - scale_factor) * 100

        print(
            f"Iteration {iteration+1:2d}: Capacity = {discharge_capacity:6.2f} Ah, "
            f"Scale = {scale_factor:.4f}, Error = {error_percent:6.3f}%"
        )

        # Check convergence
        if 1 - TOLERANCE < scale_factor < 1 + TOLERANCE:
            print("-" * 80)
            print(f"✓ Converged after {iteration+1} iterations!")
            print(f"  Final capacity: {discharge_capacity:.2f} Ah")
            print(f"  Target capacity: {target_capacity_Ah} Ah")
            print(f"  Error: {error_percent:.4f}%")

            # Extract OCV limits from calibration cycles
            ocv_100 = float(sol_capacity.cycles[1]["Terminal voltage [V]"].entries[-1])
            ocv_0 = float(sol_capacity.cycles[3]["Terminal voltage [V]"].entries[-1])

            print(f"\nCalibrated OCV window:")
            print(f"  OCV at 100% SOC: {ocv_100:.4f} V")
            print(f"  OCV at 0% SOC: {ocv_0:.4f} V")

            # Update final parameters
            default_params.update(
                {
                    "Open-circuit voltage at 100% SOC [V]": ocv_100,
                    "Open-circuit voltage at 0% SOC [V]": ocv_0,
                },
                check_already_exists=False,
            )

            break

        # Update electrode width to scale capacity
        # Capacity scales linearly with electrode area (width in this case)
        new_width = default_params["Electrode width [m]"] / scale_factor

        default_params.update(
            {
                "Electrode width [m]": new_width,
                "Nominal cell capacity [A.h]": discharge_capacity / scale_factor,
            },
            check_already_exists=False,
        )

    else:
        # Loop completed without convergence
        print("-" * 80)
        print(f"⚠️  Warning: Did not converge after {MAX_ITERATIONS} iterations")
        print(f"  Final capacity: {discharge_capacity:.2f} Ah")
        print(f"  Target capacity: {target_capacity_Ah} Ah")
        print(f"  Final error: {error_percent:.3f}%")

    print("=" * 80)
    print(f"\nFinal calibrated parameters:")
    print(f"  Electrode width: {default_params['Electrode width [m]']*1000:.2f} mm")
    print(f"  Nominal capacity: {default_params['Nominal cell capacity [A.h]']:.2f} Ah")

    print("\n" + "=" * 80)
    print("DCIR SIMULATION")
    print("=" * 80)

    print(f"\nDCIR Test Configuration:")
    print(
        f"  Temperature: {simulation_config.get('temperature_K', 298.15)-273.15:.0f}°C"
    )
    print(f"  Initial SOC: {simulation_config.get('initial_soc', 0.5)*100:.0f}%")
    print(f"  C-rate: {simulation_config.get('c_rate', 1.0)}C")
    print(f"  Pulse duration: {simulation_config.get('duration_s', 30)}s")
    # Create DCIR experiment: 1s rest, then pulse
    experiment = pybamm.Experiment(
        [
            ("Rest for 1 seconds"),
            (
                f"Discharge at {simulation_config.get('c_rate', 1.0)}C for {simulation_config.get('duration_s', 30)} seconds or until {cell_design.lower_voltage_cutoff.value} V",
                "Rest for 600 seconds",
            ),
        ],
        period="0.01 second",  # 10ms sampling for accurate DCIR measurement
    )

    # Create model and simulation
    model = pybamm.lithium_ion.SPMe(options=model_options)
    # Define mesh points for spatial discretization
    var_pts = {
        "x_n": 10,
        "x_s": 10,
        "x_p": 10,
        "r_n": 10,
        "r_p": 10,
    }

    sim = pybamm.Simulation(
        model, parameter_values=default_params, experiment=experiment, var_pts=var_pts
    )

    # Run simulation
    print(f"\nRunning DCIR simulation...")
    solver = pybamm.IDAKLUSolver(
        atol=1e-4,
        rtol=1e-4,
        output_variables=[
            "Time [s]",
            "Terminal voltage [V]",
            "Current [A]",
            "Discharge capacity [A.h]",
            "Volume-averaged cell temperature [K]",
            "Power [W]",
        ],
    )

    initial_soc = simulation_config.get("initial_soc", 0.5)
    if not 0 <= initial_soc <= 1:
        raise ValueError(f"Initial SOC ({initial_soc}) must be in range [0, 1]")

    # Run baseline DCIR
    print("\n Running baseline DCIR...")
    try:
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        # Calculate baseline DCIR values
        dcir_df = []
        for t_point in [0.01, 0.1, 1.0, 10.0, 30.0]:
            t_idx = np.argmin(np.abs(solution["Time [s]"].entries - (1.0 + t_point)))
            v_rest = solution["Terminal voltage [V]"].entries[0]
            v_pulse = solution["Terminal voltage [V]"].entries[t_idx]
            i_amplitude = (
                simulation_config.get("c_rate", 1.0) * kpis.nominal_capacity.value
            )
            contact_resistance = simulation_config.get("contact_resistance", 1e-5)
            dcir_ohm = abs(v_pulse - v_rest) / i_amplitude + contact_resistance
            dcir_mohm = dcir_ohm * 1000
            dcir_df.append({"time": t_point, "dcir": dcir_mohm, "voltage": v_pulse})

    except pybamm.SolverError as e:
        print(f"DCIR simulation failed: {e}")
        print("This may be due to:")
        print("  - Voltage cutoff reached during discharge pulse")
        print("  - Temperature limit exceeded")
        print("  - C-rate too high for the configuration")
        raise
    print("✓ DCIR simulation completed!")

    return dcir_df
