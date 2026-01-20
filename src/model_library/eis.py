"""
EIS (Electrochemical Impedance Spectroscopy) Module

PyBaMM-EIS based simulation that computes impedance spectra for battery models.
Uses the pybamm-eis package for frequency-domain analysis.
"""

import numpy as np
import pybamm
import pybammeis
import matplotlib.pyplot as plt


def convert_functions(obj):
    """
    Recursively convert function specifications to callable Python functions.

    Handles function specs with the format:
        {
            "type": "function",
            "expression": "m_ref * np.exp(E_r / R * (1/298.15 - 1/T)) * c_e**0.5",
            "arguments": {
                "c_e": {"description": "Electrolyte concentration", "unit": "mol/m3"},
                "T": {"description": "Temperature", "unit": "K"}
            },
            "constants": {
                "m_ref": 6.48e-07,
                "E_r": 17800
            }
        }

    Args:
        obj: Dictionary (or nested structure) potentially containing function specs

    Returns:
        Same structure with function specs converted to callables
    """
    if isinstance(obj, dict):
        # Check if this is a function specification (supports both "expression" and "value" keys)
        if obj.get("type") == "function" and ("expression" in obj or "value" in obj):
            return _create_function_from_spec(obj)
        # Recursively process nested dicts
        return {k: convert_functions(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_functions(item) for item in obj]
    return obj


def _create_function_from_spec(func_spec: dict):
    """
    Convert a JSON function specification to a callable Python function.

    Args:
        func_spec: Dictionary with type="function", expression/value, and optional arguments/constants

    Returns:
        Callable function
    """
    # Support both "expression" and "value" keys for the expression string
    expression = func_spec.get("expression") or func_spec.get("value", "0")
    arguments = func_spec.get("arguments", {})
    constants = func_spec.get("constants", {})

    # Try to parse as simple constant first
    try:
        const_value = float(expression)
        return lambda *args, **kwargs: const_value
    except (ValueError, TypeError):
        pass

    # Extract constants from arguments (arguments with "value" field are constants)
    arg_constants = {}
    runtime_args = []
    for name, arg_def in arguments.items():
        if isinstance(arg_def, dict) and "value" in arg_def:
            arg_constants[name] = arg_def["value"]
        else:
            runtime_args.append(name)

    def evaluated_function(*args, **kwargs):
        # Build namespace with numpy, pybamm, math functions, and constants
        namespace = {
            "np": np,
            "pybamm": pybamm,
            "exp": np.exp,
            "sqrt": np.sqrt,
            "log": np.log,
            **constants,
            **arg_constants,
        }
        # Map positional args to runtime argument names
        for i, name in enumerate(runtime_args):
            if i < len(args):
                namespace[name] = args[i]
        namespace.update(kwargs)
        return eval(expression, namespace)

    return evaluated_function


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


def _load_ocp_data_from_material(material_data: dict, electrode_type: str) -> tuple:
    """Load OCP data from material dictionary."""
    ocv_data = material_data["electrochemical_properties"]["ocv"]["data"]

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


def run_eis(
    cell_design_manifest: dict,
    eis_config: dict | None = None,
) -> dict:
    """
    Run EIS (Electrochemical Impedance Spectroscopy) simulation.

    This function computes the impedance spectrum of a battery cell across
    a range of frequencies using PyBaMM-EIS.

    Args:
        cell_design_manifest: Cell design parameters dictionary

        eis_config: EIS configuration dictionary containing:
            - frequencies: Array of frequencies to evaluate [Hz] (default: logspace(-3, 4, 50))
            - soc: State of charge for EIS measurement [0-1] (default: 0.5)
            - temperature_K: Temperature [K] (default: 298.15)
            - method: Solver method - 'direct', 'prebicgstab', or 'bicgstab' (default: 'direct')
            - contact_resistance: Contact resistance [Ohm] (default: 1e-5)

    Returns:
        Dictionary containing:
            - frequencies_Hz: Array of frequencies [Hz]
            - impedance: Complex impedance array [Ohm]
            - Z_real: Real part of impedance [Ohm]
            - Z_imag: Imaginary part of impedance [Ohm]
            - Z_magnitude: Magnitude of impedance [Ohm]
            - Z_phase_deg: Phase angle [degrees]
            - soc: State of charge used
            - temperature_K: Temperature used [K]
            - success: Boolean indicating if simulation succeeded
            - error: Error message if failed (optional)
            - config: Configuration used

    Example:
        >>> config = {
        ...     "frequencies": np.logspace(-2, 4, 30),
        ...     "soc": 0.5,
        ...     "temperature_K": 298.15,
        ... }
        >>> result = run_eis(cell_design_manifest, config)
        >>> print(f"Impedance at 1 Hz: {result['Z_real'][15]:.4f} + {result['Z_imag'][15]:.4f}j Ohm")
    """
    if eis_config is None:
        eis_config = {}

    # Default configuration
    frequencies = eis_config.get("frequencies", np.logspace(-3, 4, 50))
    soc = eis_config.get("soc", 0.5)
    temperature_K = eis_config.get("temperature_K", 298.15)
    method = eis_config.get("method", "direct")
    contact_resistance = eis_config.get("contact_resistance", 1e-5)

    print("\n" + "=" * 80)
    print("EIS SIMULATION")
    print("=" * 80)
    print(f"Frequency range: {frequencies.min():.2e} - {frequencies.max():.2e} Hz")
    print(f"Number of frequencies: {len(frequencies)}")
    print(f"SOC: {soc * 100:.1f}%")
    print(f"Temperature: {temperature_K - 273.15:.1f}°C")
    print(f"Method: {method}")

    # Build PyBaMM parameters from manifest
    params = _build_eis_parameters(cell_design_manifest, eis_config)

    # Set up model options for EIS
    # Note: EIS requires "surface form": "differential" for proper impedance calculation
    model_options = {
        "surface form": "differential",
        "contact resistance": "true",
    }

    print("\nBuilding EIS model...")

    try:
        # Create the battery model (DFN recommended for EIS)
        model = pybamm.lithium_ion.DFN(options=model_options)

        # Create EIS simulation
        eis_sim = pybammeis.EISSimulation(model, parameter_values=params)

        print(f"Solving EIS at SOC = {soc * 100:.1f}%...")

        # Solve for impedance spectrum
        # Note: pybammeis expects the model to be at a specific SOC
        # We set initial concentrations based on SOC
        impedance = eis_sim.solve(frequencies, method=method)

        # Extract real and imaginary parts
        Z_real = np.real(impedance)
        Z_imag = np.imag(impedance)
        Z_magnitude = np.abs(impedance)
        Z_phase_rad = np.angle(impedance)
        Z_phase_deg = np.degrees(Z_phase_rad)

        print(f"  Completed: {len(frequencies)} frequency points")
        print(
            f"  Z at 1 Hz: {np.interp(1.0, frequencies, Z_real):.4f} + "
            f"{np.interp(1.0, frequencies, Z_imag):.4f}j Ohm"
        )

        result = {
            "frequencies_Hz": frequencies,
            "impedance": impedance,
            "Z_real": Z_real,
            "Z_imag": Z_imag,
            "Z_magnitude": Z_magnitude,
            "Z_phase_deg": Z_phase_deg,
            "soc": soc,
            "temperature_K": temperature_K,
            "success": True,
            "config": eis_config,
            "eis_simulation": eis_sim,  # Include for plotting
        }

        print("\n" + "=" * 80)
        print("EIS SIMULATION COMPLETE")
        print("=" * 80)

        return result

    except Exception as e:
        print(f"\nEIS simulation failed: {str(e)}")
        return {
            "frequencies_Hz": frequencies,
            "impedance": np.array([]),
            "Z_real": np.array([]),
            "Z_imag": np.array([]),
            "Z_magnitude": np.array([]),
            "Z_phase_deg": np.array([]),
            "soc": soc,
            "temperature_K": temperature_K,
            "success": False,
            "error": str(e),
            "config": eis_config,
        }


def _build_eis_parameters(
    cell_design_manifest: dict, eis_config: dict
) -> pybamm.ParameterValues:
    """Build PyBaMM parameters for EIS simulation from cell design manifest."""
    default_params = pybamm.ParameterValues("Chen2020")

    cell_design = dict2obj(cell_design_manifest["cell_design"])
    kpis = dict2obj(cell_design_manifest["kpis"])

    soc = eis_config.get("soc", 0.5)
    temperature_K = eis_config.get("temperature_K", 298.15)
    contact_resistance = eis_config.get("contact_resistance", 1e-5)

    print("\nBuilding EIS parameters from manifest...")

    # Get material data from cell_design
    pos_material_data = cell_design_manifest["cell_design"]["positive_electrode"][
        "material"
    ]
    neg_material_data = cell_design_manifest["cell_design"]["negative_electrode"][
        "material"
    ]

    # Convert to dict2obj and apply function conversion
    pos_material = dict2obj(convert_functions(pos_material_data))
    neg_material = dict2obj(convert_functions(neg_material_data))

    # Load OCP data
    pos_ocp, sto_p_0, sto_p_100 = _load_ocp_data_from_material(
        pos_material_data, "positive"
    )
    neg_ocp, sto_n_0, sto_n_100 = _load_ocp_data_from_material(
        neg_material_data, "negative"
    )

    # Calculate stoichiometry at given SOC
    # At SOC=0: pos at sto_p_0 (high), neg at sto_n_0 (low)
    # At SOC=1: pos at sto_p_100 (low), neg at sto_n_100 (high)
    sto_p = sto_p_0 + soc * (sto_p_100 - sto_p_0)
    sto_n = sto_n_0 + soc * (sto_n_100 - sto_n_0)

    print(f"  SOC: {soc * 100:.1f}%")
    print(f"  Positive stoichiometry: {sto_p:.4f}")
    print(f"  Negative stoichiometry: {sto_n:.4f}")

    # Positive electrode parameters
    number_of_coated_sides = 2
    pos_electrode = cell_design.positive_electrode

    # Cell and electrode geometry
    cell_params = {
        "Nominal cell capacity [A.h]": kpis.nominal_capacity.value,
        "Number of electrodes connected in parallel to make a cell": (
            pos_electrode.count.value
            * cell_design.jelly_roll.count.value
            * number_of_coated_sides
        ),
        "Electrode height [m]": pos_electrode.height.value / 1000,
        "Electrode width [m]": pos_electrode.width.value / 1000,
    }

    # Positive electrode
    positive_electrode_params = {
        "Positive electrode thickness [m]": pos_electrode.coating.thickness.value / 1e6,
        "Positive electrode porosity": pos_electrode.coating.porosity.value,
        "Positive electrode active material volume fraction": pos_electrode.coating.active_material_volume_fraction.value,
        "Positive electrode Bruggeman coefficient (electrode)": pos_electrode.coating.bruggeman_coefficient.value,
        "Positive electrode Bruggeman coefficient (electrolyte)": pos_electrode.coating.bruggeman_coefficient.value,
        "Positive electrode conductivity [S.m-1]": pos_material.physical_properties.conductivity.value,
        "Positive particle diffusivity [m2.s-1]": pos_material.electrochemical_properties.diffusion_coefficient.value,
        "Positive electrode OCP [V]": pos_ocp,
        "Positive electrode charge transfer coefficient": pos_material.electrochemical_properties.charge_transfer_coefficient.value,
        "Positive electrode exchange-current density [A.m-2]": pos_material.electrochemical_properties.exchange_current_density,
        "Positive particle radius [m]": pos_material.physical_properties.particle_size.d50.value
        / 1e6,
        "Maximum concentration in positive electrode [mol.m-3]": pos_material.electrochemical_properties.max_lithium_concentration.value,
        "Initial concentration in positive electrode [mol.m-3]": (
            sto_p
            * pos_material.electrochemical_properties.max_lithium_concentration.value
        ),
    }

    positive_cc_params = {
        "Positive current collector thickness [m]": pos_electrode.foil.thickness.value
        / 1e6,
        "Positive current collector conductivity [S.m-1]": pos_electrode.foil.material.electrical_conductivity.value,
    }

    # Negative electrode
    neg_electrode = cell_design.negative_electrode

    negative_electrode_params = {
        "Negative electrode thickness [m]": neg_electrode.coating.thickness.value / 1e6,
        "Negative electrode porosity": neg_electrode.coating.porosity.value,
        "Negative electrode active material volume fraction": neg_electrode.coating.active_material_volume_fraction.value,
        "Negative electrode Bruggeman coefficient (electrode)": neg_electrode.coating.bruggeman_coefficient.value,
        "Negative electrode Bruggeman coefficient (electrolyte)": neg_electrode.coating.bruggeman_coefficient.value,
        "Negative electrode conductivity [S.m-1]": neg_material.physical_properties.conductivity.value,
        "Negative particle diffusivity [m2.s-1]": neg_material.electrochemical_properties.diffusion_coefficient.value,
        "Negative electrode OCP [V]": neg_ocp,
        "Negative electrode charge transfer coefficient": neg_material.electrochemical_properties.charge_transfer_coefficient.value,
        "Negative electrode exchange-current density [A.m-2]": neg_material.electrochemical_properties.exchange_current_density,
        "Negative particle radius [m]": neg_material.physical_properties.particle_size.d50.value
        / 1e6,
        "Maximum concentration in negative electrode [mol.m-3]": neg_material.electrochemical_properties.max_lithium_concentration.value,
        "Initial concentration in negative electrode [mol.m-3]": (
            sto_n
            * neg_material.electrochemical_properties.max_lithium_concentration.value
        ),
    }

    negative_cc_params = {
        "Negative current collector thickness [m]": neg_electrode.foil.thickness.value
        / 1e6,
        "Negative current collector conductivity [S.m-1]": neg_electrode.foil.material.electrical_conductivity.value,
    }

    # Separator
    separator = cell_design.separator
    separator_params = {
        "Separator thickness [m]": separator.thickness.value / 1e6,
        "Separator porosity": separator.porosity.value,
        "Separator Bruggeman coefficient (electrolyte)": separator.material.thermal_properties.bruggeman_coefficient.value,
    }

    # Electrolyte
    electrolyte = cell_design.electrolyte.material
    electrolyte_params = {
        "Cation transference number": electrolyte.transference_number.reference_value.value,
        "Electrolyte conductivity [S.m-1]": electrolyte.ionic_conductivity.reference_value.value
        * 0.1,
        "Electrolyte diffusivity [m2.s-1]": electrolyte.ionic_diffusivity.reference_value.value
        * 1e-4,
        "Initial concentration in electrolyte [mol.m-3]": electrolyte.composition.nominal_concentration.value
        * 1000,
        "Thermodynamic factor": electrolyte.thermodynamic_factor.reference_value.value,
    }

    # Operating conditions
    operating_params = {
        "Ambient temperature [K]": temperature_K,
        "Initial temperature [K]": temperature_K,
        "Reference temperature [K]": 298.15,
        "Contact resistance [Ohm]": contact_resistance,
        "Current function [A]": kpis.nominal_capacity.value,  # 1C current reference
    }

    # Combine all parameters
    all_params = {
        **cell_params,
        **positive_electrode_params,
        **positive_cc_params,
        **negative_electrode_params,
        **negative_cc_params,
        **separator_params,
        **electrolyte_params,
        **operating_params,
    }

    default_params.update(all_params, check_already_exists=False)
    print("  Parameters loaded")

    return default_params


def nyquist_plot(result: dict, ax=None, **kwargs):
    """
    Create a Nyquist plot from EIS simulation results.

    Args:
        result: Dictionary returned by run_eis()
        ax: Matplotlib axes (optional, creates new figure if None)
        **kwargs: Additional arguments passed to plt.plot()

    Returns:
        Matplotlib axes object
    """
    import matplotlib.pyplot as plt

    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 6))

    if not result["success"]:
        ax.text(
            0.5,
            0.5,
            f"Simulation failed:\n{result.get('error', 'Unknown error')}",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        return ax

    Z_real = result["Z_real"]
    Z_imag = result["Z_imag"]

    # Default plot style
    plot_kwargs = {"marker": "o", "markersize": 4, "linewidth": 1}
    plot_kwargs.update(kwargs)

    ax.plot(Z_real, -Z_imag, **plot_kwargs)
    ax.set_xlabel("Z' (Real) [Ω]")
    ax.set_ylabel("-Z'' (Imaginary) [Ω]")
    ax.set_title(f"Nyquist Plot (SOC = {result['soc']*100:.0f}%)")
    ax.grid(True, alpha=0.3)
    ax.set_aspect("equal")

    return ax


def bode_plot(result: dict, axes=None, **kwargs):
    """
    Create Bode plots (magnitude and phase) from EIS simulation results.

    Args:
        result: Dictionary returned by run_eis()
        axes: Tuple of (ax_mag, ax_phase) or None to create new figure
        **kwargs: Additional arguments passed to plt.plot()

    Returns:
        Tuple of (ax_magnitude, ax_phase)
    """

    if axes is None:
        fig, (ax_mag, ax_phase) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    else:
        ax_mag, ax_phase = axes

    if not result["success"]:
        ax_mag.text(
            0.5,
            0.5,
            f"Simulation failed:\n{result.get('error', 'Unknown error')}",
            ha="center",
            va="center",
            transform=ax_mag.transAxes,
        )
        return ax_mag, ax_phase

    frequencies = result["frequencies_Hz"]
    Z_magnitude = result["Z_magnitude"]
    Z_phase_deg = result["Z_phase_deg"]

    # Default plot style
    plot_kwargs = {"marker": "o", "markersize": 3, "linewidth": 1}
    plot_kwargs.update(kwargs)

    # Magnitude plot
    ax_mag.loglog(frequencies, Z_magnitude, **plot_kwargs)
    ax_mag.set_ylabel("|Z| [Ω]")
    ax_mag.set_title(f"Bode Plot (SOC = {result['soc']*100:.0f}%)")
    ax_mag.grid(True, alpha=0.3, which="both")

    # Phase plot
    ax_phase.semilogx(frequencies, Z_phase_deg, **plot_kwargs)
    ax_phase.set_xlabel("Frequency [Hz]")
    ax_phase.set_ylabel("Phase [°]")
    ax_phase.grid(True, alpha=0.3, which="both")

    plt.tight_layout()

    return ax_mag, ax_phase
