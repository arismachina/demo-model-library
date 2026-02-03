"""
DFN Drive Cycle Simulation with Degradation Module

Combines drive cycle simulation with coupled degradation mechanisms:
- SEI growth (solvent-diffusion limited)
- Lithium plating (partially reversible)
- Particle cracking and swelling
- Stress-driven loss of active material

Uses Doyle-Fuller-Newman (DFN) model for detailed electrochemical analysis
with range and energy estimation.
"""

import pybamm
import numpy as np


# Known drive cycle distances (km)
DRIVE_CYCLE_DISTANCES = {
    # Automotive cycles
    "Auto WLTP": 23.266,
    "Auto US06": 12.8,
    "Track Nurburgring": 20.8,
}

# Typical speeds for aerial vehicles (km/h)
AERIAL_SPEEDS = {
    "Aero Quad Drone": 40,
    "Aero UAV": 80,
    "Aero eVTOL": 150,
}


def _build_pybamm_params_with_degradation(
    cell_design: dict, simulation_config: dict
) -> tuple:
    """
    Build PyBaMM parameters from cell design manifest with degradation options.

    Returns:
        Tuple of (calibrated_params, model_options)
    """
    print("\nBuilding DFN model parameters with degradation...")

    # Select base parameter set
    cathode_material = cell_design["positive_electrode"]["coating"]["formulation"][
        "primary_active_material"
    ]["name"]

    # Use O'Kane2022 for degradation parameters
    if simulation_config.get("use_okane2022_params", False):
        default_params = pybamm.ParameterValues("OKane2022")
        print("  Using O'Kane2022 parameter set (includes degradation)")
    elif "LFP" in cathode_material.upper():
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
        "Positive electrode specific heat capacity [J.kg-1.K-1]": 700.0,  # Typical for NMC composite electrodes
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
        "Positive current collector specific heat capacity [J.kg-1.K-1]": (
            pos_electrode["foil"]["material"]["specific_heat"]["value"] * 1000
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
        "Negative electrode specific heat capacity [J.kg-1.K-1]": 700.0,  # Typical for graphite composite electrodes
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
        "Negative current collector specific heat capacity [J.kg-1.K-1]": (
            neg_electrode["foil"]["material"]["specific_heat"]["value"] * 1000
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
        "Separator specific heat capacity [J.kg-1.K-1]": (
            separator["material"]["thermal_properties"]["specific_heat_capacity"][
                "value"
            ]
        ),
    }

    # Thermal parameters
    thermal_params = {
        "Reference temperature [K]": 298.15,
        "Total heat transfer coefficient [W.m-2.K-1]": simulation_config[
            "total_heat_transfer_coefficient_W_m2K"
        ],
        "Cell cooling surface area [m2]": simulation_config["cooling_surface_area_m2"],
        "Cell volume [m3]": cell_design["cell_volume"]["value"] / 1000.0,
    }

    # Operating conditions
    operating_conditions = {
        "Ambient temperature [K]": simulation_config["ambient_temperature_K"],
        "Initial temperature [K]": simulation_config["initial_temperature_K"],
        "Contact resistance [Ohm]": simulation_config["contact_resistance_Ohm"],
        "Upper voltage cut-off [V]": simulation_config["upper_voltage_cutoff_V"],
        "Lower voltage cut-off [V]": simulation_config["lower_voltage_cutoff_V"],
    }

    # Degradation parameters
    degradation_params = {}
    if simulation_config.get("initial_sei_thickness_m") is not None:
        degradation_params["Initial SEI thickness [m]"] = simulation_config[
            "initial_sei_thickness_m"
        ]
    else:
        # Default SEI thickness if not specified (5 nm)
        degradation_params["Initial SEI thickness [m]"] = 5e-9

    if simulation_config.get("sei_partial_molar_volume_m3_mol") is not None:
        degradation_params["SEI partial molar volume [m3.mol-1]"] = simulation_config[
            "sei_partial_molar_volume_m3_mol"
        ]
    else:
        # Default SEI partial molar volume (typical value)
        degradation_params["SEI partial molar volume [m3.mol-1]"] = 9.585e-5

    if simulation_config.get("typical_plated_lithium_concentration_mol_m3") is not None:
        degradation_params["Typical plated lithium concentration [mol.m-3]"] = (
            simulation_config["typical_plated_lithium_concentration_mol_m3"]
        )
    else:
        # Default typical plated lithium concentration (typical value for Li metal)
        degradation_params["Typical plated lithium concentration [mol.m-3]"] = 1000.0

    if simulation_config.get("lithium_metal_partial_molar_volume_m3_mol") is not None:
        degradation_params["Lithium metal partial molar volume [m3.mol-1]"] = (
            simulation_config["lithium_metal_partial_molar_volume_m3_mol"]
        )
    else:
        # Default Li metal partial molar volume (typical value from literature)
        degradation_params["Lithium metal partial molar volume [m3.mol-1]"] = 1.3e-5

    if simulation_config.get("sei_resistivity_Ohm_m") is not None:
        degradation_params["SEI resistivity [Ohm.m]"] = simulation_config[
            "sei_resistivity_Ohm_m"
        ]
    else:
        # Default SEI resistivity (typical value for SEI layer)
        degradation_params["SEI resistivity [Ohm.m]"] = 2.5e5

    if simulation_config.get("sei_growth_activation_energy_J_mol") is not None:
        degradation_params["SEI growth activation energy [J.mol-1]"] = (
            simulation_config["sei_growth_activation_energy_J_mol"]
        )
    else:
        # Default SEI growth activation energy (typical value from literature)
        degradation_params["SEI growth activation energy [J.mol-1]"] = 5e4

    if simulation_config.get("sei_solvent_diffusivity_m2_s") is not None:
        degradation_params["SEI solvent diffusivity [m2.s-1]"] = simulation_config[
            "sei_solvent_diffusivity_m2_s"
        ]
    else:
        # Default SEI solvent diffusivity (typical value for solvent diffusion through SEI)
        degradation_params["SEI solvent diffusivity [m2.s-1]"] = 2.5e-22

    if simulation_config.get("bulk_solvent_concentration_mol_m3") is not None:
        degradation_params["Bulk solvent concentration [mol.m-3]"] = simulation_config[
            "bulk_solvent_concentration_mol_m3"
        ]
    else:
        # Default bulk solvent concentration in electrolyte (typical for EC in LiPF6)
        degradation_params["Bulk solvent concentration [mol.m-3]"] = 2000.0

    if simulation_config.get("sei_reaction_exchange_current_density_A_m2") is not None:
        degradation_params["SEI reaction exchange current density [A.m-2]"] = (
            simulation_config["sei_reaction_exchange_current_density_A_m2"]
        )
    else:
        # Default SEI reaction exchange current density
        # Controls rate of SEI formation reaction at the electrode surface
        # Typical value from O'Kane2022: 1.5e-7 A/m²
        degradation_params["SEI reaction exchange current density [A.m-2]"] = 1.5e-7

    if simulation_config.get("sei_open_circuit_potential_V") is not None:
        degradation_params["SEI open-circuit potential [V]"] = simulation_config[
            "sei_open_circuit_potential_V"
        ]
    else:
        # Default SEI open-circuit potential
        # Thermodynamic potential for SEI formation reaction
        # Typical value from O'Kane2022: 0.4 V vs Li/Li+
        degradation_params["SEI open-circuit potential [V]"] = 0.4

    if simulation_config.get("ec_diffusivity_m2_s") is not None:
        degradation_params["EC diffusivity [m2.s-1]"] = simulation_config[
            "ec_diffusivity_m2_s"
        ]
    else:
        # Default EC (ethylene carbonate) diffusivity through SEI
        # Controls rate of solvent transport to reaction sites
        # Typical value from O'Kane2022: 2e-18 m²/s
        degradation_params["EC diffusivity [m2.s-1]"] = 2e-18

    if simulation_config.get("ec_initial_concentration_mol_m3") is not None:
        degradation_params["EC initial concentration in electrolyte [mol.m-3]"] = (
            simulation_config["ec_initial_concentration_mol_m3"]
        )
    else:
        # Default initial EC concentration in electrolyte
        # Typical value from O'Kane2022: 4541 mol/m³
        degradation_params["EC initial concentration in electrolyte [mol.m-3]"] = 4541.0

    if simulation_config.get("exchange_current_density_for_stripping_A_m2") is not None:
        degradation_params["Exchange-current density for stripping [A.m-2]"] = (
            simulation_config["exchange_current_density_for_stripping_A_m2"]
        )
    else:
        # Default exchange-current density for lithium stripping (typical value)
        degradation_params["Exchange-current density for stripping [A.m-2]"] = 0.001

    if simulation_config.get("lithium_plating_transfer_coefficient") is not None:
        degradation_params["Lithium plating transfer coefficient"] = simulation_config[
            "lithium_plating_transfer_coefficient"
        ]
    else:
        # Default transfer coefficient for lithium plating reaction (typical value)
        degradation_params["Lithium plating transfer coefficient"] = 0.5

    if simulation_config.get("exchange_current_density_for_plating_A_m2") is not None:
        degradation_params["Exchange-current density for plating [A.m-2]"] = (
            simulation_config["exchange_current_density_for_plating_A_m2"]
        )
    else:
        # Default exchange-current density for lithium plating (typical value)
        degradation_params["Exchange-current density for plating [A.m-2]"] = 0.001

    if simulation_config.get("ratio_lithium_moles_to_sei_moles") is not None:
        degradation_params["Ratio of lithium moles to SEI moles"] = simulation_config[
            "ratio_lithium_moles_to_sei_moles"
        ]
    else:
        # Default ratio of lithium consumed to SEI formed (stoichiometry of SEI reaction)
        # Typical value is 1.0 for reactions like: 2Li + EC → Li2CO3 + C2H4
        degradation_params["Ratio of lithium moles to SEI moles"] = 1.0

    if simulation_config.get("dead_lithium_decay_rate_s_inv") is not None:
        degradation_params["Dead lithium decay rate [s-1]"] = simulation_config[
            "dead_lithium_decay_rate_s_inv"
        ]
    else:
        # Default decay rate for dead lithium back to active lithium
        # Controls reversibility in partially reversible plating models
        # Typical value: 1e-6 s^-1 (slow decay, mostly irreversible)
        degradation_params["Dead lithium decay rate [s-1]"] = 1.0e-6

    if simulation_config.get("initial_plated_lithium_concentration_mol_m3") is not None:
        degradation_params["Initial plated lithium concentration [mol.m-3]"] = (
            simulation_config["initial_plated_lithium_concentration_mol_m3"]
        )
    else:
        # Default initial plated lithium concentration
        # Must be small non-zero value to avoid division by zero in discretization
        # Using 1e-6 mol/m³ (essentially zero but avoids numerical issues)
        degradation_params["Initial plated lithium concentration [mol.m-3]"] = 1e-6

    if simulation_config.get("negative_electrode_initial_crack_length_m") is not None:
        degradation_params["Negative electrode initial crack length [m]"] = (
            simulation_config["negative_electrode_initial_crack_length_m"]
        )
    else:
        # Default initial crack length for negative electrode
        # Must be small non-zero to avoid division by zero in discretization
        # Using 1e-9 m (1 nm, essentially no cracks but avoids numerical issues)
        degradation_params["Negative electrode initial crack length [m]"] = 1e-9

    if simulation_config.get("positive_electrode_initial_crack_length_m") is not None:
        degradation_params["Positive electrode initial crack length [m]"] = (
            simulation_config["positive_electrode_initial_crack_length_m"]
        )
    else:
        # Default initial crack length for positive electrode
        # Must be small non-zero to avoid division by zero in discretization
        # Using 1e-9 m (1 nm, essentially no cracks but avoids numerical issues)
        degradation_params["Positive electrode initial crack length [m]"] = 1e-9

    if simulation_config.get("negative_electrode_cracking_rate") is not None:
        degradation_params["Negative electrode cracking rate"] = simulation_config[
            "negative_electrode_cracking_rate"
        ]
    else:
        # Default crack propagation rate for negative electrode particles
        # Controls rate of crack growth under mechanical stress (Paris' law parameter)
        # Typical value: 3.9e-20 m (from PyBaMM O'Kane2022 parameters for graphite)
        degradation_params["Negative electrode cracking rate"] = 3.9e-20

    if simulation_config.get("positive_electrode_cracking_rate") is not None:
        degradation_params["Positive electrode cracking rate"] = simulation_config[
            "positive_electrode_cracking_rate"
        ]
    else:
        # Default crack propagation rate for positive electrode particles
        # Controls rate of crack growth under mechanical stress (Paris' law parameter)
        # Typical value: 3.9e-20 m (baseline value, material-dependent)
        degradation_params["Positive electrode cracking rate"] = 3.9e-20

    if (
        simulation_config.get("negative_electrode_partial_molar_volume_m3_mol")
        is not None
    ):
        degradation_params["Negative electrode partial molar volume [m3.mol-1]"] = (
            simulation_config["negative_electrode_partial_molar_volume_m3_mol"]
        )
    else:
        # Default partial molar volume for negative electrode active material
        # For graphite (LixC6): typical value 3.1e-6 m³/mol (from PyBaMM parameters)
        # Controls volume change during lithiation/delithiation
        degradation_params["Negative electrode partial molar volume [m3.mol-1]"] = (
            3.1e-6
        )

    if (
        simulation_config.get("positive_electrode_partial_molar_volume_m3_mol")
        is not None
    ):
        degradation_params["Positive electrode partial molar volume [m3.mol-1]"] = (
            simulation_config["positive_electrode_partial_molar_volume_m3_mol"]
        )
    else:
        # Default partial molar volume for positive electrode active material
        # For NMC materials: typical value -7.28e-7 m³/mol (negative = contraction on lithiation)
        # Material-dependent: LFP, LCO have different values
        degradation_params["Positive electrode partial molar volume [m3.mol-1]"] = (
            -7.28e-7
        )

    if simulation_config.get("negative_electrode_youngs_modulus_Pa") is not None:
        degradation_params["Negative electrode Young's modulus [Pa]"] = (
            simulation_config["negative_electrode_youngs_modulus_Pa"]
        )
    else:
        # Default Young's modulus for negative electrode (graphite)
        # Typical value: 15 GPa = 15e9 Pa (from PyBaMM O'Kane2022 parameters)
        # Controls mechanical stiffness and stress generation during volume changes
        degradation_params["Negative electrode Young's modulus [Pa]"] = 15e9

    if simulation_config.get("positive_electrode_youngs_modulus_Pa") is not None:
        degradation_params["Positive electrode Young's modulus [Pa]"] = (
            simulation_config["positive_electrode_youngs_modulus_Pa"]
        )
    else:
        # Default Young's modulus for positive electrode (NMC)
        # Typical value: 375 GPa = 375e9 Pa (from PyBaMM O'Kane2022 parameters)
        # NMC is much stiffer than graphite
        degradation_params["Positive electrode Young's modulus [Pa]"] = 375e9

    if simulation_config.get("negative_electrode_poissons_ratio") is not None:
        degradation_params["Negative electrode Poisson's ratio"] = simulation_config[
            "negative_electrode_poissons_ratio"
        ]
    else:
        # Default Poisson's ratio for negative electrode (graphite)
        # Typical value: 0.3 (dimensionless, relates lateral to axial strain)
        degradation_params["Negative electrode Poisson's ratio"] = 0.3

    if simulation_config.get("positive_electrode_poissons_ratio") is not None:
        degradation_params["Positive electrode Poisson's ratio"] = simulation_config[
            "positive_electrode_poissons_ratio"
        ]
    else:
        # Default Poisson's ratio for positive electrode (NMC)
        # Typical value: 0.3 (dimensionless, common for ceramics)
        degradation_params["Positive electrode Poisson's ratio"] = 0.3

    if simulation_config.get("negative_electrode_paris_law_constant_b") is not None:
        degradation_params["Negative electrode Paris' law constant b"] = (
            simulation_config["negative_electrode_paris_law_constant_b"]
        )
    else:
        # Default Paris' law exponent b for negative electrode (graphite)
        # In Paris' law: da/dN = C * (ΔK)^b, where b is the exponent
        # Typical value: 1.0 (from PyBaMM O'Kane2022 parameters)
        degradation_params["Negative electrode Paris' law constant b"] = 1.0

    if simulation_config.get("positive_electrode_paris_law_constant_b") is not None:
        degradation_params["Positive electrode Paris' law constant b"] = (
            simulation_config["positive_electrode_paris_law_constant_b"]
        )
    else:
        # Default Paris' law exponent b for positive electrode (NMC)
        # Controls sensitivity of crack growth to stress intensity
        # Typical value: 1.0 (baseline value)
        degradation_params["Positive electrode Paris' law constant b"] = 1.0

    if simulation_config.get("negative_electrode_paris_law_constant_m") is not None:
        degradation_params["Negative electrode Paris' law constant m"] = (
            simulation_config["negative_electrode_paris_law_constant_m"]
        )
    else:
        # Default Paris' law exponent m for negative electrode (graphite)
        # In Paris' law: da/dN = C * (ΔK)^m, where m controls stress sensitivity
        # From PyBaMM O'Kane2022 parameters: 1.0
        degradation_params["Negative electrode Paris' law constant m"] = 1.0

    if simulation_config.get("positive_electrode_paris_law_constant_m") is not None:
        degradation_params["Positive electrode Paris' law constant m"] = (
            simulation_config["positive_electrode_paris_law_constant_m"]
        )
    else:
        # Default Paris' law exponent m for positive electrode (NMC)
        # Material-dependent parameter for crack growth sensitivity
        # Typical value: 1.0
        degradation_params["Positive electrode Paris' law constant m"] = 1.0

    if (
        simulation_config.get("negative_electrode_lam_constant_proportional")
        is not None
    ):
        degradation_params[
            "Negative electrode LAM constant proportional term [s-1]"
        ] = simulation_config["negative_electrode_lam_constant_proportional"]
    else:
        # Default LAM rate constant for negative electrode (graphite)
        # Controls rate of loss of active material due to particle stress/cracking
        # From PyBaMM O'Kane2022: 1e-4 s^-1
        degradation_params[
            "Negative electrode LAM constant proportional term [s-1]"
        ] = 1e-4

    if (
        simulation_config.get("positive_electrode_lam_constant_proportional")
        is not None
    ):
        degradation_params[
            "Positive electrode LAM constant proportional term [s-1]"
        ] = simulation_config["positive_electrode_lam_constant_proportional"]
    else:
        # Default LAM rate constant for positive electrode (NMC)
        # Material-dependent rate of active material loss
        # Typical value: 1e-4 s^-1
        degradation_params[
            "Positive electrode LAM constant proportional term [s-1]"
        ] = 1e-4

    if simulation_config.get("negative_electrode_lam_constant_exponential") is not None:
        degradation_params["Negative electrode LAM constant exponential term"] = (
            simulation_config["negative_electrode_lam_constant_exponential"]
        )
    else:
        # Default LAM exponential term for negative electrode
        # Stress sensitivity factor in exponential LAM kinetics
        # From PyBaMM O'Kane2022: 2.0 (dimensionless)
        degradation_params["Negative electrode LAM constant exponential term"] = 2.0

    if simulation_config.get("positive_electrode_lam_constant_exponential") is not None:
        degradation_params["Positive electrode LAM constant exponential term"] = (
            simulation_config["positive_electrode_lam_constant_exponential"]
        )
    else:
        # Default LAM exponential term for positive electrode
        # Stress sensitivity factor for cathode material loss
        # Typical value: 2.0 (dimensionless)
        degradation_params["Positive electrode LAM constant exponential term"] = 2.0

    if simulation_config.get("negative_electrode_critical_stress_Pa") is not None:
        degradation_params["Negative electrode critical stress [Pa]"] = (
            simulation_config["negative_electrode_critical_stress_Pa"]
        )
    else:
        # Default critical stress for negative electrode (graphite)
        # Stress threshold above which LAM becomes significant
        # From PyBaMM O'Kane2022: 60 MPa = 60e6 Pa
        degradation_params["Negative electrode critical stress [Pa]"] = 60e6

    if simulation_config.get("positive_electrode_critical_stress_Pa") is not None:
        degradation_params["Positive electrode critical stress [Pa]"] = (
            simulation_config["positive_electrode_critical_stress_Pa"]
        )
    else:
        # Default critical stress for positive electrode (NMC)
        # Material-dependent stress threshold for LAM activation
        # Typical value: 60 MPa = 60e6 Pa
        degradation_params["Positive electrode critical stress [Pa]"] = 60e6

    if (
        simulation_config.get(
            "negative_electrode_reference_concentration_for_free_of_deformation"
        )
        is not None
    ):
        degradation_params[
            "Negative electrode reference concentration for free of deformation [mol.m-3]"
        ] = simulation_config[
            "negative_electrode_reference_concentration_for_free_of_deformation"
        ]
    else:
        # Default reference concentration for stress-free state in negative electrode
        # Concentration at which particle has zero stress (no volume change)
        # For graphite: typically half of maximum concentration
        # From PyBaMM O'Kane2022: 0.5 * c_max (will be calculated from material)
        # Typical value: ~15000 mol/m³ for graphite
        degradation_params[
            "Negative electrode reference concentration for free of deformation [mol.m-3]"
        ] = 0.0  # Will use default calculation if 0

    if (
        simulation_config.get(
            "positive_electrode_reference_concentration_for_free_of_deformation"
        )
        is not None
    ):
        degradation_params[
            "Positive electrode reference concentration for free of deformation [mol.m-3]"
        ] = simulation_config[
            "positive_electrode_reference_concentration_for_free_of_deformation"
        ]
    else:
        # Default reference concentration for stress-free state in positive electrode
        # Concentration at which NMC particle has zero stress
        # Material-dependent: typically around 0.5 * c_max
        # Typical value: ~25000 mol/m³ for NMC
        degradation_params[
            "Positive electrode reference concentration for free of deformation [mol.m-3]"
        ] = 0.0  # Will use default calculation if 0

    if (
        simulation_config.get("negative_electrode_number_of_cracks_per_unit_area")
        is not None
    ):
        degradation_params[
            "Negative electrode number of cracks per unit area [m-2]"
        ] = simulation_config["negative_electrode_number_of_cracks_per_unit_area"]
    else:
        # Default number of cracks per unit area for negative electrode
        # Crack density in graphite particles
        # From PyBaMM O'Kane2022: 3.16e15 cracks/m² (very high density)
        degradation_params[
            "Negative electrode number of cracks per unit area [m-2]"
        ] = 3.16e15

    if (
        simulation_config.get("positive_electrode_number_of_cracks_per_unit_area")
        is not None
    ):
        degradation_params[
            "Positive electrode number of cracks per unit area [m-2]"
        ] = simulation_config["positive_electrode_number_of_cracks_per_unit_area"]
    else:
        # Default number of cracks per unit area for positive electrode
        # Crack density in NMC particles (typically lower than graphite)
        # Material-dependent, typical value: 3.16e15 cracks/m²
        degradation_params[
            "Positive electrode number of cracks per unit area [m-2]"
        ] = 3.16e15

    if simulation_config.get("negative_electrode_initial_crack_width_m") is not None:
        degradation_params["Negative electrode initial crack width [m]"] = (
            simulation_config["negative_electrode_initial_crack_width_m"]
        )
    else:
        # Default initial crack width for negative electrode
        # Width of cracks in graphite particles
        # From PyBaMM O'Kane2022: 1e-9 m (1 nm, very narrow)
        degradation_params["Negative electrode initial crack width [m]"] = 1e-9

    if simulation_config.get("positive_electrode_initial_crack_width_m") is not None:
        degradation_params["Positive electrode initial crack width [m]"] = (
            simulation_config["positive_electrode_initial_crack_width_m"]
        )
    else:
        # Default initial crack width for positive electrode
        # Width of cracks in NMC particles
        # Typical value: 1e-9 m (1 nm)
        degradation_params["Positive electrode initial crack width [m]"] = 1e-9

    if simulation_config.get("initial_sei_on_cracks_thickness_m") is not None:
        degradation_params["Initial SEI on cracks thickness [m]"] = simulation_config[
            "initial_sei_on_cracks_thickness_m"
        ]
    else:
        # Default initial SEI thickness on crack surfaces
        # SEI layer that forms on freshly exposed crack surfaces
        # Typically starts at zero or very thin (1 nm)
        # From PyBaMM O'Kane2022: 1e-9 m
        degradation_params["Initial SEI on cracks thickness [m]"] = 1e-9

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
        **degradation_params,
    }

    default_params.update(pybamm_params, check_already_exists=False)

    # Model options with degradation
    model_options = {
        "calculate discharge energy": "true",
        "cell geometry": "arbitrary",
        "thermal": "lumped",
        "contact resistance": "true",
        # Degradation options
        "SEI": simulation_config.get("sei_model", "solvent-diffusion limited"),
        "SEI porosity change": simulation_config.get("sei_porosity_change", "true"),
        "lithium plating": simulation_config.get(
            "lithium_plating", "partially reversible"
        ),
        "lithium plating porosity change": simulation_config.get(
            "lithium_plating_porosity_change", "true"
        ),
        "particle mechanics": simulation_config.get(
            "particle_mechanics", ("swelling and cracking", "swelling only")
        ),
        "SEI on cracks": simulation_config.get("sei_on_cracks", "true"),
        "loss of active material": simulation_config.get(
            "loss_of_active_material", "stress-driven"
        ),
    }

    print(f"  Degradation options enabled:")
    print(f"    - SEI: {model_options['SEI']}")
    print(f"    - Lithium plating: {model_options['lithium plating']}")
    print(f"    - Particle mechanics: {model_options['particle mechanics']}")
    print(f"    - SEI on cracks: {model_options['SEI on cracks']}")
    print(f"    - Loss of active material: {model_options['loss of active material']}")

    # Optional: Capacity calibration
    if simulation_config.get("skip_capacity_calibration", False):
        print("  Skipping capacity calibration (using default parameters)")
        return default_params, model_options

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

    # Use DFN for calibration with simplified degradation
    calibration_options = {
        **model_options,
        "particle mechanics": "none",  # Disable for faster calibration
        "SEI on cracks": "false",
        "loss of active material": "none",
    }
    model_capacity = pybamm.lithium_ion.DFN(options=calibration_options)

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


def _run_dfn_drive_cycle_with_degradation(
    drive_cycle: dict,
    simulation_config: dict,
    default_params: pybamm.ParameterValues,
    model_options: dict,
) -> dict:
    """
    Execute DFN simulation with degradation for drive cycle.

    Returns:
        Dict with simulation results including degradation metrics
    """
    print("\n" + "=" * 80)
    print("RUNNING DFN DRIVE CYCLE WITH DEGRADATION")
    print("=" * 80)

    time_s = np.array(drive_cycle["time_s"])
    label = drive_cycle.get("label", "drive_cycle")

    # Get custom termination thresholds
    anode_threshold = simulation_config.get("anode_potential_threshold_V")
    temp_threshold = simulation_config.get("temperature_threshold_K")
    lower_voltage = simulation_config.get("lower_voltage_cutoff_V")
    upper_voltage = simulation_config.get("upper_voltage_cutoff_V")

    # Build termination conditions
    termination_conditions = []

    if anode_threshold is not None:

        def anode_potential_cutoff(variables):
            return variables["Anode potential [V]"] - anode_threshold

        termination_conditions.append(
            pybamm.step.CustomTermination(
                "Anode potential cut-off [V]", anode_potential_cutoff
            )
        )

    if temp_threshold is not None:

        def temperature_cutoff(variables):
            return temp_threshold - variables["Volume-averaged cell temperature [K]"]

        termination_conditions.append(
            pybamm.step.CustomTermination("Temperature cut-off [K]", temperature_cutoff)
        )

    if lower_voltage is not None:

        def voltage_lower_cutoff(variables):
            return variables["Terminal voltage [V]"] - lower_voltage

        termination_conditions.append(
            pybamm.step.CustomTermination(
                "Lower voltage cut-off [V]", voltage_lower_cutoff
            )
        )

    if upper_voltage is not None:

        def voltage_upper_cutoff(variables):
            return upper_voltage - variables["Terminal voltage [V]"]

        termination_conditions.append(
            pybamm.step.CustomTermination(
                "Upper voltage cut-off [V]", voltage_upper_cutoff
            )
        )

    # Determine drive cycle type
    if "power_W" in drive_cycle:
        values = np.array(drive_cycle["power_W"])
        print(f"  Type: Power")
        print(f"  Power range: {values.min():.1f} to {values.max():.1f} W")
        drive_data = np.column_stack((time_s, values))
        if termination_conditions:
            drive_cycle_step = pybamm.step.power(
                drive_data, duration=time_s[-1], termination=termination_conditions
            )
        else:
            drive_cycle_step = pybamm.step.power(drive_data, duration=time_s[-1])
    elif "c_rate" in drive_cycle:
        values = np.array(drive_cycle["c_rate"])
        print(f"  Type: C-rate")
        print(f"  C-rate range: {values.min():.3f} to {values.max():.3f} C")
        drive_data = np.column_stack((time_s, values))
        if termination_conditions:
            drive_cycle_step = pybamm.step.c_rate(
                drive_data, duration=time_s[-1], termination=termination_conditions
            )
        else:
            drive_cycle_step = pybamm.step.c_rate(drive_data, duration=time_s[-1])
    else:
        raise ValueError("drive_cycle must contain either 'power_W' or 'c_rate'")

    print(f"  Label: {label}")
    print(f"  Duration: {time_s[-1]:.1f} s ({time_s[-1]/60:.1f} min)")
    print(f"  Data points: {len(time_s)}")
    if termination_conditions:
        print(f"  Custom terminations: {len(termination_conditions)}")

    period = simulation_config.get("period", "1 second")
    experiment = pybamm.Experiment([drive_cycle_step], period=period)

    # Create DFN model with degradation
    model = pybamm.lithium_ion.DFN(options=model_options)

    # Add anode potential variable
    model.variables["Anode potential [V]"] = model.variables[
        "Negative electrode surface potential difference at separator interface [V]"
    ]

    # Setup simulation with higher mesh resolution for DFN
    var_pts = simulation_config.get(
        "var_pts",
        {
            "x_n": 10,
            "x_s": 10,
            "x_p": 10,
            "r_n": 30,  # Higher for particle mechanics
            "r_p": 30,
        },
    )

    # Output variables including degradation metrics
    output_vars = [
        "Time [s]",
        "Terminal voltage [V]",
        "Current [A]",
        "Discharge capacity [A.h]",
        "Discharge energy [W.h]",
        "Volume-averaged cell temperature [K]",
        "Terminal power [W]",
        "Anode potential [V]",
        # Degradation variables
        "Loss of lithium inventory [%]",
        "Loss of active material in negative electrode [%]",
        "Loss of active material in positive electrode [%]",
        "Total lithium lost [mol]",
        "Loss of capacity to negative SEI [A.h]",
        "Loss of capacity to negative SEI on cracks [A.h]",
        "Loss of capacity to negative lithium plating [A.h]",
        "Total capacity lost to side reactions [A.h]",
        "X-averaged negative electrode porosity",
        "X-averaged positive electrode porosity",
        "Throughput capacity [A.h]",
    ]

    solver = pybamm.IDAKLUSolver(
        atol=1e-4,
        rtol=1e-4,
        output_variables=output_vars,
    )

    sim = pybamm.Simulation(
        model,
        parameter_values=default_params,
        experiment=experiment,
        var_pts=var_pts,
    )

    initial_soc = simulation_config.get("initial_soc", 0.8)

    try:
        print(f"  Running DFN simulation (initial SOC: {initial_soc*100:.0f}%)...")
        print("  This may take longer due to degradation models...")
        solution = sim.solve(initial_soc=initial_soc, solver=solver)

        termination_reason = getattr(solution, "termination", "completed")

        # Extract basic variables
        try:
            discharge_capacity = solution["Discharge capacity [A.h]"].entries
            soc = (
                initial_soc
                - discharge_capacity / default_params["Nominal cell capacity [A.h]"]
            )
        except (KeyError, AttributeError) as e:
            print(f"  Warning: Could not compute SOC - {str(e)[:50]}")
            discharge_capacity = None
            soc = None

        # Build result dict
        result = {
            "experiment_label": label,
            "termination_reason": termination_reason,
            "success": True,
        }

        # Add standard variables
        result["time_s"] = solution["Time [s]"].entries
        result["voltage_V"] = solution["Terminal voltage [V]"].entries
        result["current_A"] = solution["Current [A]"].entries
        result["temperature_K"] = solution[
            "Volume-averaged cell temperature [K]"
        ].entries
        result["power_W"] = solution["Terminal power [W]"].entries
        result["anode_potential_V"] = solution["Anode potential [V]"].entries

        if discharge_capacity is not None:
            result["capacity_Ah"] = discharge_capacity
        if soc is not None:
            result["soc"] = soc

        try:
            result["energy_Wh"] = solution["Discharge energy [W.h]"].entries
        except (KeyError, AttributeError):
            pass

        # Extract degradation variables
        degradation_data = {}
        try:
            degradation_data["LLI_pct"] = solution[
                "Loss of lithium inventory [%]"
            ].entries
            degradation_data["LAM_neg_pct"] = solution[
                "Loss of active material in negative electrode [%]"
            ].entries
            degradation_data["LAM_pos_pct"] = solution[
                "Loss of active material in positive electrode [%]"
            ].entries
            degradation_data["Li_lost_mol"] = solution[
                "Total lithium lost [mol]"
            ].entries
            degradation_data["Q_SEI_Ah"] = solution[
                "Loss of capacity to negative SEI [A.h]"
            ].entries
            degradation_data["Q_SEI_cracks_Ah"] = solution[
                "Loss of capacity to negative SEI on cracks [A.h]"
            ].entries
            degradation_data["Q_plating_Ah"] = solution[
                "Loss of capacity to negative lithium plating [A.h]"
            ].entries
            degradation_data["Q_side_reactions_Ah"] = solution[
                "Total capacity lost to side reactions [A.h]"
            ].entries
            degradation_data["porosity_neg"] = solution[
                "X-averaged negative electrode porosity"
            ].entries
            degradation_data["porosity_pos"] = solution[
                "X-averaged positive electrode porosity"
            ].entries
            degradation_data["throughput_Ah"] = solution[
                "Throughput capacity [A.h]"
            ].entries
            result["degradation"] = degradation_data
            print("  Degradation data extracted successfully")
        except (KeyError, AttributeError) as e:
            print(f"  Warning: Some degradation variables unavailable - {str(e)[:50]}")

        n_points = len(result.get("time_s", []))
        print(f"  Completed: {n_points} data points")
        if termination_reason != "completed" and termination_reason != "final time":
            print(f"  Termination: {termination_reason}")

        if n_points == 0 or "voltage_V" not in result:
            result["success"] = False
            result["error"] = "Simulation produced insufficient data"
            print("  Warning: Insufficient simulation data")

        return result

    except pybamm.SolverError as e:
        print(f"  Failed: {str(e)[:100]}")
        return {
            "experiment_label": label,
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        import traceback

        error_msg = str(e) if str(e) else repr(e)
        full_traceback = traceback.format_exc()
        print(f"  Unexpected error: {error_msg[:100]}")
        print(f"  Exception type: {type(e).__name__}")
        print(f"  Full traceback:\n{full_traceback}")
        return {
            "experiment_label": label,
            "success": False,
            "error": f"Unexpected error: {error_msg}",
            "traceback": full_traceback,
        }


def estimate_speed_from_power(
    power_W: np.ndarray,
    vehicle_params: dict,
    vehicle_type: str = "ground",
) -> tuple[np.ndarray, dict]:
    """
    Estimate vehicle speed from mechanical power using physics models.

    Args:
        power_W: Array of mechanical power values [W]
        vehicle_params: Dict with vehicle parameters
        vehicle_type: "ground" or "aircraft"

    Returns:
        Tuple of (speed_m_s array, metadata dict)
    """
    weight_kg = vehicle_params["weight_kg"]
    Cd = vehicle_params.get("drag_coefficient", 0.3)
    A = vehicle_params.get("frontal_area_m2", 2.0)
    eta = vehicle_params.get("drivetrain_efficiency", 0.85)
    rho = vehicle_params.get("air_density_kg_m3", 1.225)
    Crr = vehicle_params.get("rolling_resistance", 0.01)
    L_D = vehicle_params.get("lift_to_drag", None)

    g = 9.81
    W = weight_kg * g

    P_mech = np.abs(power_W) * eta
    drag_coef = 0.5 * rho * Cd * A

    speeds = np.zeros_like(power_W, dtype=float)

    for i, P in enumerate(P_mech):
        if P <= 0:
            speeds[i] = 0
            continue

        if vehicle_type == "ground":
            F_roll = Crr * W
            coeffs = [drag_coef, 0, F_roll, -P]
            roots = np.roots(coeffs)
            real_positive = [r.real for r in roots if np.isreal(r) and r.real > 0]
            speeds[i] = real_positive[0] if real_positive else 0
        else:
            if L_D is not None:
                coeffs = [drag_coef, 0, W / L_D, -P]
                roots = np.roots(coeffs)
                real_positive = [r.real for r in roots if np.isreal(r) and r.real > 0]
                speeds[i] = real_positive[0] if real_positive else 0
            else:
                if drag_coef > 0:
                    speeds[i] = (P / drag_coef) ** (1 / 3)
                else:
                    speeds[i] = 0

    valid_speeds = speeds[speeds > 0]
    metadata = {
        "avg_speed_m_s": float(np.mean(valid_speeds)) if len(valid_speeds) > 0 else 0,
        "max_speed_m_s": float(np.max(speeds)),
        "avg_speed_kmh": (
            float(np.mean(valid_speeds) * 3.6) if len(valid_speeds) > 0 else 0
        ),
        "max_speed_kmh": float(np.max(speeds) * 3.6),
        "vehicle_type": vehicle_type,
    }

    return speeds, metadata


def run_drive_cycle_with_degradation(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run a drive cycle simulation with DFN model and coupled degradation mechanisms.

    This function automatically detects single-cycle or multi-cycle mode based on config:
    - Single-cycle mode: If max_cycles is not specified or equals 1
    - Multi-cycle mode: If max_cycles > 1 in simulation_config

    Multi-cycle mode runs ONE FLAT SIMULATION with repeated drive cycles until:
    - SoH drops below threshold, OR
    - Max cycles reached, OR
    - Total simulation time limit reached

    This function combines comprehensive drive cycle analysis with degradation tracking:
    - SEI growth (solvent-diffusion limited)
    - Lithium plating (partially reversible)
    - Particle cracking and swelling
    - Stress-driven loss of active material
    - Porosity changes due to side reactions

    Args:
        cell_design: Cell design parameters dictionary (from manifest)
        simulation_config: Simulation configuration containing:
            - All parameters from spmet_drive.run_drive_cycle()
            - Additional degradation options:
                - use_okane2022_params: Use O'Kane2022 parameter set (bool)
                - skip_capacity_calibration: Skip calibration for speed (bool)
                - sei_model: SEI model type (default: "solvent-diffusion limited")
                - sei_porosity_change: Enable SEI porosity change (default: "true")
                - lithium_plating: Li plating model (default: "partially reversible")
                - lithium_plating_porosity_change: Enable (default: "true")
                - particle_mechanics: Tuple for neg/pos electrodes
                - sei_on_cracks: Enable SEI on cracks (default: "true")
                - loss_of_active_material: LAM model (default: "stress-driven")
                - var_pts: Mesh points dict (default: higher resolution for DFN)
            - Multi-cycle mode options (triggers multi-cycle if max_cycles > 1):
                - max_cycles: Maximum number of cycles to simulate (int)
                - soh_threshold: Stop if SoH falls below this % (float, default: 80.0)
                - max_simulation_time_s: Stop if total sim time exceeds limit (float, optional)
                - save_interval: Sample interval for degradation tracking (int, default: 10)

    Returns:
        Single-cycle mode - Dictionary containing:
            - All outputs from spmet_drive.run_drive_cycle()
            - degradation: Dict with degradation timeseries
            - degradation_summary: Dict with final degradation metrics

        Multi-cycle mode - Dictionary containing:
            - cycle_history: DataFrame with per-cycle metrics (sampled at save_interval)
            - summary: Dict with final multi-cycle metrics
            - config: Simulation configuration used
    """
    # Detect mode: multi-cycle if max_cycles > 1
    max_cycles = simulation_config.get("max_cycles", 1)

    if max_cycles > 1:
        # Multi-cycle mode - ONE FLAT SIMULATION with repeated drive cycles
        return _run_flat_multi_cycle_simulation(cell_design, simulation_config)

    # Single-cycle mode - continue with original implementation
    return _run_single_cycle_degradation_internal(cell_design, simulation_config)


def _run_single_cycle_degradation_internal(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Internal function for single-cycle degradation simulation.
    Called by run_drive_cycle_with_degradation() in single-cycle mode.
    """
    # Validate inputs
    if "drive_cycle" not in simulation_config:
        raise ValueError("simulation_config must contain 'drive_cycle'")

    drive_cycle = simulation_config["drive_cycle"]
    if "time_s" not in drive_cycle:
        raise ValueError("drive_cycle must contain 'time_s'")
    if "c_rate" not in drive_cycle and "power_W" not in drive_cycle:
        raise ValueError("drive_cycle must contain either 'c_rate' or 'power_W'")

    # Get cell parameters
    cell_nominal_capacity = cell_design["nominal_capacity"]["value"]
    cell_nominal_voltage = cell_design.get("nominal_voltage", {}).get("value")

    # Handle pack-to-cell power conversion
    pack_energy_kWh = simulation_config.get("pack_max_energy_kWh", None)
    pack_max_power_kW = simulation_config.get("pack_rated_peak_power_kW")
    pack_nominal_voltage = simulation_config.get("pack_nominal_voltage_V")

    if pack_energy_kWh is not None and "power_W" in drive_cycle:
        cells_series = pack_nominal_voltage / cell_nominal_voltage
        cells_parallel = (
            pack_energy_kWh * 1000 / (pack_nominal_voltage * cell_nominal_capacity)
        )
        total_cells = cells_series * cells_parallel

        pack_power_W = np.array(drive_cycle["power_W"])
        cell_power_W = pack_power_W / total_cells

        drive_cycle = {**drive_cycle, "power_W": cell_power_W}
        simulation_config = {**simulation_config, "drive_cycle": drive_cycle}

        print(
            f"\n  Pack config: {cells_series:.0f}S{cells_parallel:.0f}P ({total_cells:.0f} cells)"
        )
        print(
            f"  Pack power range: {pack_power_W.min():.1f} to {pack_power_W.max():.1f} W"
        )
        print(
            f"  Cell power range: {cell_power_W.min():.1f} to {cell_power_W.max():.1f} W"
        )

    # Build PyBaMM parameters with degradation
    default_params, model_options = _build_pybamm_params_with_degradation(
        cell_design, simulation_config
    )

    # Run simulation
    sim_result = _run_dfn_drive_cycle_with_degradation(
        drive_cycle=drive_cycle,
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
        "time_s": sim_result["time_s"],
        "voltage_V": sim_result["voltage_V"],
        "current_A": sim_result["current_A"],
        "power_W": sim_result["power_W"],
        "temperature_K": sim_result["temperature_K"],
        "capacity_Ah": sim_result["capacity_Ah"],
        "soc": sim_result["soc"],
        "energy_Wh": sim_result["energy_Wh"],
        "anode_potential_V": sim_result["anode_potential_V"],
    }

    # Add degradation timeseries if available
    if "degradation" in sim_result:
        timeseries["degradation"] = sim_result["degradation"]

    termination_reason = sim_result.get("termination_reason", "completed")

    # Calculate summary statistics
    sim_time = sim_result["time_s"]
    sim_voltage = sim_result["voltage_V"]
    sim_current = sim_result["current_A"]
    sim_power = sim_result["power_W"]
    sim_temp = sim_result["temperature_K"]
    sim_capacity = sim_result["capacity_Ah"]

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
        "data_points": len(sim_time),
    }

    # Energy analysis
    dt = np.diff(sim_time)
    power_mid = (sim_power[:-1] + sim_power[1:]) / 2

    discharge_mask = power_mid > 0
    regen_mask = power_mid < 0

    energy_discharged = float(
        np.sum(power_mid[discharge_mask] * dt[discharge_mask]) / 3600
    )
    energy_regen = float(-np.sum(power_mid[regen_mask] * dt[regen_mask]) / 3600)
    energy_net = energy_discharged - energy_regen

    capacity_used = float(sim_capacity[-1] - sim_capacity[0])
    initial_soc = simulation_config.get("initial_soc", 0.8)
    soc_change = capacity_used / cell_nominal_capacity * 100

    energy_analysis = {
        "energy_discharged_Wh": energy_discharged,
        "energy_regenerated_Wh": energy_regen,
        "energy_net_Wh": energy_net,
        "capacity_used_Ah": capacity_used,
        "soc_change_pct": soc_change,
        "regeneration_ratio_pct": (
            energy_regen / energy_discharged * 100 if energy_discharged > 0 else 0
        ),
    }

    # Degradation summary
    degradation_summary = {}
    if "degradation" in sim_result:
        deg = sim_result["degradation"]
        degradation_summary = {
            "LLI_final_pct": float(deg["LLI_pct"][-1]),
            "LAM_neg_final_pct": float(deg["LAM_neg_pct"][-1]),
            "LAM_pos_final_pct": float(deg["LAM_pos_pct"][-1]),
            "Li_lost_final_mol": float(deg["Li_lost_mol"][-1]),
            "Q_SEI_final_Ah": float(deg["Q_SEI_Ah"][-1]),
            "Q_SEI_cracks_final_Ah": float(deg["Q_SEI_cracks_Ah"][-1]),
            "Q_plating_final_Ah": float(deg["Q_plating_Ah"][-1]),
            "Q_side_reactions_final_Ah": float(deg["Q_side_reactions_Ah"][-1]),
            "porosity_neg_initial": float(deg["porosity_neg"][0]),
            "porosity_neg_final": float(deg["porosity_neg"][-1]),
            "porosity_neg_change": float(
                deg["porosity_neg"][-1] - deg["porosity_neg"][0]
            ),
            "porosity_pos_initial": float(deg["porosity_pos"][0]),
            "porosity_pos_final": float(deg["porosity_pos"][-1]),
            "throughput_final_Ah": float(deg["throughput_Ah"][-1]),
        }

    # Range analysis (same as spmet_drive)
    cycle_duration_s = summary["duration_s"]
    label = drive_cycle.get("label", "drive_cycle")

    vehicle_params = simulation_config.get("vehicle_params")
    has_vehicle_params = (
        vehicle_params is not None or "vehicle_weight_kg" in simulation_config
    )

    if vehicle_params is None and "vehicle_weight_kg" in simulation_config:
        vehicle_params = {
            "weight_kg": simulation_config["vehicle_weight_kg"],
            "drag_coefficient": simulation_config.get("vehicle_drag_coefficient", 0.3),
            "frontal_area_m2": simulation_config.get("vehicle_frontal_area_m2", 2.0),
            "rolling_resistance": simulation_config.get(
                "vehicle_rolling_resistance", 0.01
            ),
            "drivetrain_efficiency": simulation_config.get(
                "vehicle_drivetrain_efficiency", 0.85
            ),
        }

    speed_timeseries = None
    speed_metadata = None
    physics_distance_km = None

    cycle_distance_km = drive_cycle.get("distance_km")
    is_aerial = label.startswith("Aero") if cycle_distance_km is None else False

    if has_vehicle_params and vehicle_params is not None:
        power_for_vehicle = pack_power_W if "pack_power_W" in locals() else sim_power
        vehicle_type = "aircraft" if is_aerial else "ground"
        speed_timeseries, speed_metadata = estimate_speed_from_power(
            power_for_vehicle, vehicle_params, vehicle_type
        )

        speed_mid = (speed_timeseries[:-1] + speed_timeseries[1:]) / 2
        distance_m = float(np.sum(speed_mid * dt))
        physics_distance_km = distance_m / 1000

        if cycle_distance_km is None:
            cycle_distance_km = physics_distance_km

    if cycle_distance_km is None:
        cycle_distance_km = DRIVE_CYCLE_DISTANCES.get(label)

    if cycle_distance_km is None and label in AERIAL_SPEEDS:
        avg_speed_kmh = AERIAL_SPEEDS[label]
        cycle_distance_km = avg_speed_kmh * (cycle_duration_s / 3600)
        is_aerial = True

    min_soc = simulation_config.get("min_soc", 0.10)
    max_soc = simulation_config.get("max_soc", 0.90)

    available_capacity = cell_nominal_capacity * (initial_soc - min_soc)
    usable_capacity = cell_nominal_capacity * (max_soc - min_soc)

    cycles_possible = available_capacity / capacity_used if capacity_used > 0 else 0
    full_charge_cycles = usable_capacity / capacity_used if capacity_used > 0 else 0

    range_analysis = {
        "cycle_label": label,
        "cycle_duration_s": cycle_duration_s,
        "cycle_distance_km": cycle_distance_km,
        "is_aerial": is_aerial,
        "initial_soc": initial_soc,
        "min_soc": min_soc,
        "max_soc": max_soc,
        "available_capacity_Ah": available_capacity,
        "usable_capacity_Ah": usable_capacity,
        "capacity_per_cycle_Ah": capacity_used,
        "energy_per_cycle_Wh": energy_net,
        "cycles_possible": cycles_possible,
    }

    if cycle_distance_km and cycle_distance_km > 0:
        range_km = cycles_possible * cycle_distance_km
        full_range_km = full_charge_cycles * cycle_distance_km
        avg_speed_kmh = cycle_distance_km / cycle_duration_s * 3600

        range_analysis.update(
            {
                "avg_speed_kmh": avg_speed_kmh,
                "energy_per_km_Wh": energy_net / cycle_distance_km,
                "capacity_per_km_Ah": capacity_used / cycle_distance_km,
                "range_km": range_km,
                "range_miles": range_km * 0.621371,
                "full_charge_range_km": full_range_km,
                "full_charge_range_miles": full_range_km * 0.621371,
            }
        )

    drive_time_s = cycles_possible * cycle_duration_s
    full_charge_time_s = full_charge_cycles * cycle_duration_s

    time_label = "flight" if is_aerial else "drive"
    range_analysis.update(
        {
            f"{time_label}_time_min": drive_time_s / 60,
            f"{time_label}_time_hr": drive_time_s / 3600,
            f"full_charge_{time_label}_time_min": full_charge_time_s / 60,
            f"full_charge_{time_label}_time_hr": full_charge_time_s / 3600,
        }
    )

    if speed_timeseries is not None:
        timeseries["speed_m_s"] = speed_timeseries
        timeseries["speed_kmh"] = speed_timeseries * 3.6

    if speed_metadata is not None:
        range_analysis["vehicle_physics"] = {
            "vehicle_type": speed_metadata["vehicle_type"],
            "avg_speed_kmh": speed_metadata["avg_speed_kmh"],
            "max_speed_kmh": speed_metadata["max_speed_kmh"],
            "physics_distance_km": physics_distance_km,
        }

    return {
        "success": True,
        "timeseries": timeseries,
        "summary": summary,
        "energy_analysis": energy_analysis,
        "range_analysis": range_analysis,
        "degradation_summary": degradation_summary,
        "termination_reason": termination_reason,
        "config": simulation_config,
    }


def _run_flat_multi_cycle_simulation(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run ONE FLAT SIMULATION with repeated drive cycles and degradation tracking.

    This creates a single PyBaMM experiment with N repeated drive cycle steps,
    simulated in one go with continuous degradation evolution. Much more efficient
    than running N separate simulations.

    Stops when:
    - SoH drops below threshold, OR
    - Max cycles reached, OR
    - Total simulation time limit reached (if specified)

    Control parameters from simulation_config:
    - max_cycles: Number of drive cycle repetitions (default: 1000)
    - soh_threshold: Stop when SoH < this % (default: 80.0)
    - max_simulation_time_s: Total sim time limit in seconds (default: None = unlimited)
    - save_interval: Sampling interval for cycle history (default: 10)

    Returns:
        Dict with:
            - cycle_history: Sampled metrics at save_interval
            - summary: Final statistics
            - timeseries: Full degradation timeseries
            - stop_reason: 'soh_threshold', 'max_cycles', 'time_limit', or 'completed'
    """
    import pybamm

    nominal_capacity_Ah = cell_design["nominal_capacity"]["value"]

    # Extract control parameters
    max_cycles = simulation_config.get("max_cycles", 1000)
    soh_threshold = simulation_config.get("soh_threshold", 80.0)
    max_simulation_time_s = simulation_config.get("max_simulation_time_s", None)
    save_interval = simulation_config.get("save_interval", 10)

    # Set default degradation options if not specified
    config_with_defaults = simulation_config.copy()
    config_with_defaults.setdefault("sei_model", "solvent-diffusion limited")
    config_with_defaults.setdefault("sei_porosity_change", "true")
    config_with_defaults.setdefault("lithium_plating", "none")
    config_with_defaults.setdefault("lithium_plating_porosity_change", "false")
    config_with_defaults.setdefault("particle_mechanics", "none")
    config_with_defaults.setdefault("sei_on_cracks", "false")
    config_with_defaults.setdefault("loss_of_active_material", "none")

    print("=" * 80)
    print("FLAT MULTI-CYCLE DEGRADATION SIMULATION")
    print("=" * 80)
    print(f"Mode: ONE continuous simulation with {max_cycles} repeated drive cycles")
    print(f"Target SoH threshold: {soh_threshold}%")
    print(f"Nominal capacity: {nominal_capacity_Ah:.2f} Ah")
    if max_simulation_time_s:
        print(
            f"Max simulation time: {max_simulation_time_s:.1f} s ({max_simulation_time_s/3600:.2f} hr)"
        )
    print(f"\nActive degradation mechanisms:")
    print(f"  • SEI: {config_with_defaults['sei_model']}")
    print(f"  • Lithium plating: {config_with_defaults['lithium_plating']}")
    print(f"  • Particle mechanics: {config_with_defaults['particle_mechanics']}")
    print(f"  • SEI on cracks: {config_with_defaults['sei_on_cracks']}")
    print(
        f"  • Loss of active material: {config_with_defaults['loss_of_active_material']}"
    )
    print("=" * 80)

    # Build degradation parameters and model options
    default_params, model_options = _build_pybamm_params_with_degradation(
        cell_design, config_with_defaults
    )

    # Create drive cycle step
    drive_cycle = config_with_defaults["drive_cycle"]
    time_s = np.array(drive_cycle["time_s"])
    cycle_duration_s = time_s[-1]

    # Determine drive cycle type and create step
    if "power_W" in drive_cycle:
        values = np.array(drive_cycle["power_W"])
        drive_data = np.column_stack((time_s, values))
        drive_step = pybamm.step.power(drive_data, duration=cycle_duration_s)
        print(f"\nDrive cycle: Power profile")
        print(f"  Duration: {cycle_duration_s:.1f} s ({cycle_duration_s/60:.1f} min)")
        print(f"  Power range: {values.min():.1f} to {values.max():.1f} W")
    elif "c_rate" in drive_cycle:
        values = np.array(drive_cycle["c_rate"])
        drive_data = np.column_stack((time_s, values))
        drive_step = pybamm.step.c_rate(drive_data, duration=cycle_duration_s)
        print(f"\nDrive cycle: C-rate profile")
        print(f"  Duration: {cycle_duration_s:.1f} s ({cycle_duration_s/60:.1f} min)")
        print(f"  C-rate range: {values.min():.3f} to {values.max():.3f} C")
    else:
        raise ValueError("drive_cycle must contain either 'power_W' or 'c_rate'")

    # Create experiment with repeated drive cycles
    experiment_steps = [drive_step] * max_cycles
    period = config_with_defaults.get("period", "1 second")
    experiment = pybamm.Experiment(experiment_steps, period=period)

    print(f"\n✓ Experiment created: {max_cycles} repeated drive cycles")
    print(f"  Total experiment duration: {max_cycles * cycle_duration_s / 3600:.2f} hr")

    # Create DFN model with degradation
    model = pybamm.lithium_ion.DFN(options=model_options)

    # Setup simulation
    var_pts = config_with_defaults.get(
        "var_pts",
        {"x_n": 10, "x_s": 10, "x_p": 10, "r_n": 30, "r_p": 30},
    )

    # Output variables for degradation tracking
    output_vars = [
        "Time [s]",
        "Terminal voltage [V]",
        "Current [A]",
        "Discharge capacity [A.h]",
        "Volume-averaged cell temperature [K]",
        "Terminal power [W]",
        # Degradation variables
        "Loss of lithium inventory [%]",
        "Loss of active material in negative electrode [%]",
        "Loss of active material in positive electrode [%]",
        "Total lithium lost [mol]",
        "Loss of capacity to negative SEI [A.h]",
        "Loss of capacity to positive SEI [A.h]",
        "Loss of capacity to negative SEI on cracks [A.h]",
        "Loss of capacity to positive SEI on cracks [A.h]",
        "Loss of capacity to lithium plating [A.h]",
        "Total lithium lost to side reactions [A.h]",
        "Negative electrode porosity",
        "Positive electrode porosity",
        "Throughput capacity [A.h]",
    ]

    sim = pybamm.Simulation(
        model,
        experiment=experiment,
        parameter_values=default_params,
        var_pts=var_pts,
        solver=pybamm.CasadiSolver(mode="safe", dt_max=60),
    )

    print(f"\n🚀 Starting flat simulation...")
    import time

    start_time = time.time()

    try:
        solution = sim.solve(initial_soc=config_with_defaults.get("initial_soc", 0.8))
        elapsed_time = time.time() - start_time
        print(
            f"\n✓ Simulation completed in {elapsed_time:.1f} s ({elapsed_time/60:.1f} min)"
        )
    except Exception as e:
        print(f"\n✗ Simulation failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "stop_reason": "error",
        }

    # Extract timeseries data
    time_full = solution["Time [s]"].data
    print(f"\n📊 Solution data points: {len(time_full)}")
    print(f"   Time shape: {time_full.shape}")
    print(f"   Time range: {time_full.flat[0]:.1f} to {time_full.flat[-1]:.1f} s")

    # Flatten if multidimensional
    time_full = time_full.flatten()

    lli_full = solution["Loss of lithium inventory [%]"].data.flatten()
    lam_neg_full = solution[
        "Loss of active material in negative electrode [%]"
    ].data.flatten()
    lam_pos_full = solution[
        "Loss of active material in positive electrode [%]"
    ].data.flatten()

    # Sum SEI from both electrodes
    if 0 in solution["Loss of capacity to negative SEI [A.h]"].data.shape:
        # Handle case with multiple entries (e.g., SEI on cracks)
        q_sei_neg_full = np.sum(
            solution["Loss of capacity to negative SEI [A.h]"].data, axis=0
        )
        q_sei_pos_full = np.sum(
            solution["Loss of capacity to positive SEI [A.h]"].data, axis=0
        )
    else:
        q_sei_neg_full = solution["Loss of capacity to negative SEI [A.h]"].data
        q_sei_pos_full = solution["Loss of capacity to positive SEI [A.h]"].data
    q_sei_full = (q_sei_neg_full + q_sei_pos_full).flatten()

    # Sum SEI on cracks from both electrodes
    if 0 in solution["Loss of capacity to negative SEI on cracks [A.h]"].data.shape:
        q_sei_cracks_neg_full = np.sum(
            solution["Loss of capacity to negative SEI on cracks [A.h]"].data, axis=0
        )
        q_sei_cracks_pos_full = np.sum(
            solution["Loss of capacity to positive SEI on cracks [A.h]"].data, axis=0
        )
    else:
        q_sei_cracks_neg_full = solution[
            "Loss of capacity to negative SEI on cracks [A.h]"
        ].data
        q_sei_cracks_pos_full = solution[
            "Loss of capacity to positive SEI on cracks [A.h]"
        ].data
    q_sei_cracks_full = (q_sei_cracks_neg_full + q_sei_cracks_pos_full).flatten()

    # Lithium plating (may not exist if disabled)
    try:
        q_plating_full = solution[
            "Loss of capacity to lithium plating [A.h]"
        ].data.flatten()
        q_side_full = solution[
            "Total lithium lost to side reactions [A.h]"
        ].data.flatten()
    except KeyError:
        # Lithium plating not enabled
        q_plating_full = np.zeros_like(time_full)
        q_side_full = (q_sei_full + q_sei_cracks_full).flatten()

    porosity_neg_full = solution["Negative electrode porosity"].data.flatten()
    porosity_pos_full = solution["Positive electrode porosity"].data.flatten()
    throughput_full = solution["Throughput capacity [A.h]"].data.flatten()

    # Sample at save_interval cycles
    cycle_indices = []
    max_time = time_full[-1]  # Actual simulation end time
    max_idx = len(time_full) - 1  # Maximum valid index

    # If we have very few data points (< 10), just use all of them
    if len(time_full) < 10:
        print(
            f"⚠️  Warning: Very few data points ({len(time_full)}). Using all available data."
        )
        # Use all available indices
        estimated_cycles = max(1, int(max_time / cycle_duration_s))
        for i in range(len(time_full)):
            cycle_num = max(1, int(time_full[i] / cycle_duration_s))
            cycle_indices.append((cycle_num, i))
    else:
        for cycle_num in range(1, max_cycles + 1):
            if cycle_num % save_interval == 0 or cycle_num == max_cycles:
                # Find index closest to end of this cycle
                target_time = cycle_num * cycle_duration_s

                # Check if target time exceeds actual simulation time
                if target_time > max_time:
                    # Use the last available index
                    idx = max_idx
                    cycle_indices.append((cycle_num, idx))
                    break
                else:
                    idx = np.argmin(np.abs(time_full - target_time))
                    # Ensure index is within bounds
                    idx = min(idx, max_idx)
                    cycle_indices.append((cycle_num, idx))

    # Build cycle history
    cycle_history = {
        "cycle_number": [],
        "soh_pct": [],
        "capacity_Ah": [],
        "fce": [],
        "energy_throughput_Wh": [],
        "total_throughput_Ah": [],
        "LLI_pct": [],
        "LAM_neg_pct": [],
        "LAM_pos_pct": [],
        "Q_SEI_Ah": [],
        "Q_SEI_cracks_Ah": [],
        "Q_plating_Ah": [],
        "porosity_neg": [],
        "porosity_pos": [],
        "elapsed_time_s": [],
    }

    stop_reason = "completed"
    final_cycle = max_cycles

    for cycle_num, idx in cycle_indices:
        # Calculate SoH
        capacity_loss = q_side_full[idx]
        current_capacity = nominal_capacity_Ah - capacity_loss
        current_soh = 100 * (current_capacity / nominal_capacity_Ah)

        # Calculate FCE
        fce = throughput_full[idx] / nominal_capacity_Ah

        # Estimate energy throughput (simplified)
        energy_throughput_Wh = (
            throughput_full[idx] * 3.7 * nominal_capacity_Ah
        )  # Rough estimate

        # Store data
        cycle_history["cycle_number"].append(cycle_num)
        cycle_history["soh_pct"].append(float(current_soh))
        cycle_history["capacity_Ah"].append(float(current_capacity))
        cycle_history["fce"].append(float(fce))
        cycle_history["energy_throughput_Wh"].append(float(energy_throughput_Wh))
        cycle_history["total_throughput_Ah"].append(float(throughput_full[idx]))
        cycle_history["LLI_pct"].append(float(lli_full[idx]))
        cycle_history["LAM_neg_pct"].append(float(lam_neg_full[idx]))
        cycle_history["LAM_pos_pct"].append(float(lam_pos_full[idx]))
        cycle_history["Q_SEI_Ah"].append(float(q_sei_full[idx]))
        cycle_history["Q_SEI_cracks_Ah"].append(float(q_sei_cracks_full[idx]))
        cycle_history["Q_plating_Ah"].append(float(q_plating_full[idx]))
        cycle_history["porosity_neg"].append(float(porosity_neg_full[idx]))
        cycle_history["porosity_pos"].append(float(porosity_pos_full[idx]))
        cycle_history["elapsed_time_s"].append(float(time_full[idx]))

        # Check SoH threshold
        if current_soh < soh_threshold:
            stop_reason = "soh_threshold"
            final_cycle = cycle_num
            print(f"\n✓ SoH threshold reached at cycle {cycle_num}!")
            break

    # Check time limit
    if max_simulation_time_s and time_full[-1] >= max_simulation_time_s:
        stop_reason = "time_limit"

    # Create summary
    final_soh = cycle_history["soh_pct"][-1]
    final_capacity = cycle_history["capacity_Ah"][-1]

    summary = {
        "total_cycles": final_cycle,
        "final_soh_pct": final_soh,
        "final_capacity_Ah": final_capacity,
        "nominal_capacity_Ah": nominal_capacity_Ah,
        "capacity_fade_Ah": nominal_capacity_Ah - final_capacity,
        "capacity_fade_pct": 100 - final_soh,
        "total_fce": cycle_history["fce"][-1],
        "total_energy_throughput_Wh": cycle_history["energy_throughput_Wh"][-1],
        "total_energy_throughput_kWh": cycle_history["energy_throughput_Wh"][-1] / 1000,
        "total_throughput_Ah": cycle_history["total_throughput_Ah"][-1],
        "total_simulation_time_s": time_full[-1],
        "total_simulation_time_hr": time_full[-1] / 3600,
        "final_LLI_pct": cycle_history["LLI_pct"][-1],
        "final_LAM_neg_pct": cycle_history["LAM_neg_pct"][-1],
        "final_LAM_pos_pct": cycle_history["LAM_pos_pct"][-1],
        "threshold_reached": final_soh < soh_threshold,
        "stop_reason": stop_reason,
        "wall_clock_time_s": elapsed_time,
    }

    # Full timeseries for detailed analysis
    timeseries = {
        "time_s": time_full,
        "LLI_pct": lli_full,
        "LAM_neg_pct": lam_neg_full,
        "LAM_pos_pct": lam_pos_full,
        "Q_SEI_Ah": q_sei_full,
        "Q_SEI_cracks_Ah": q_sei_cracks_full,
        "Q_plating_Ah": q_plating_full,
        "Q_side_reactions_Ah": q_side_full,
        "porosity_neg": porosity_neg_full,
        "porosity_pos": porosity_pos_full,
        "throughput_Ah": throughput_full,
    }

    print(f"\n{'=' * 80}")
    print(f"SIMULATION COMPLETE")
    print(f"{'=' * 80}")
    print(f"Final cycle: {final_cycle}")
    print(f"Final SoH: {final_soh:.2f}%")
    print(
        f"Capacity fade: {summary['capacity_fade_Ah']:.4f} Ah ({summary['capacity_fade_pct']:.2f}%)"
    )
    print(f"Total FCE: {summary['total_fce']:.1f}")
    print(f"Stop reason: {stop_reason}")
    print(f"{'=' * 80}")

    return {
        "success": True,
        "cycle_history": cycle_history,
        "summary": summary,
        "timeseries": timeseries,
        "stop_reason": stop_reason,
        "config": config_with_defaults,
    }


def _run_multi_cycle_degradation_internal(
    cell_design: dict,
    simulation_config: dict,
) -> dict:
    """
    Run multiple drive cycles until SoH drops below threshold or time limit reached.

    Control parameters are read from simulation_config:
    - soh_threshold: Stop when SoH drops below this (%, default: 80.0)
    - max_cycles: Maximum cycles to run (default: 1000)
    - max_simulation_time_s: Maximum total simulation time in seconds (default: None)
    - save_interval: Print progress every N cycles (default: 10)

    Args:
        cell_design: Cell design dictionary
        simulation_config: Simulation configuration with:
            - Degradation options (sei_model, lithium_plating, etc.)
            - Multi-cycle control: soh_threshold, max_cycles, max_simulation_time_s, save_interval

    Returns:
        Dict with:
            - cycle_history: DataFrame-ready dict with per-cycle metrics
            - summary: Aggregated summary statistics
            - stop_reason: Why simulation stopped ('soh_threshold', 'max_cycles', 'time_limit', or 'error')
    """
    nominal_capacity_Ah = cell_design["nominal_capacity"]["value"]

    # Set default degradation options (SEI-only) if not specified
    config_with_defaults = simulation_config.copy()
    config_with_defaults.setdefault("sei_model", "solvent-diffusion limited")
    config_with_defaults.setdefault("sei_porosity_change", "true")
    config_with_defaults.setdefault("lithium_plating", "none")
    config_with_defaults.setdefault("lithium_plating_porosity_change", "false")
    config_with_defaults.setdefault("particle_mechanics", "none")
    config_with_defaults.setdefault("sei_on_cracks", "false")
    config_with_defaults.setdefault("loss_of_active_material", "none")

    # Extract multi-cycle control parameters from config
    soh_threshold = config_with_defaults.get("soh_threshold", 80.0)
    max_cycles = config_with_defaults.get("max_cycles", 1000)
    max_simulation_time_s = config_with_defaults.get("max_simulation_time_s", None)
    save_interval = config_with_defaults.get("save_interval", 10)

    # Print simulation header
    print("=" * 80)
    print("MULTI-CYCLE DEGRADATION SIMULATION")
    print("=" * 80)
    print(f"Target SoH threshold: {soh_threshold}%")
    print(f"Nominal capacity: {nominal_capacity_Ah:.2f} Ah")
    print(f"Max cycles: {max_cycles}")
    if max_simulation_time_s:
        print(
            f"Max simulation time: {max_simulation_time_s:.1f} s ({max_simulation_time_s/3600:.2f} hr)"
        )
    print(f"\nActive degradation mechanisms:")
    print(f"  • SEI: {config_with_defaults['sei_model']}")
    print(f"  • Lithium plating: {config_with_defaults['lithium_plating']}")
    print(f"  • Particle mechanics: {config_with_defaults['particle_mechanics']}")
    print(f"  • SEI on cracks: {config_with_defaults['sei_on_cracks']}")
    print(
        f"  • Loss of active material: {config_with_defaults['loss_of_active_material']}"
    )
    print("=" * 80)

    # Storage for cycle data
    cycle_history = {
        "cycle_number": [],
        "soh_pct": [],
        "capacity_Ah": [],
        "fce": [],
        "energy_throughput_Wh": [],
        "total_throughput_Ah": [],
        "LLI_pct": [],
        "LAM_neg_pct": [],
        "LAM_pos_pct": [],
        "Q_SEI_Ah": [],
        "Q_SEI_cracks_Ah": [],
        "Q_plating_Ah": [],
        "porosity_neg": [],
        "porosity_pos": [],
        "elapsed_time_s": [],
    }

    # Cumulative tracking
    total_throughput_Ah = 0.0
    total_energy_Wh = 0.0
    current_soh = 100.0
    total_elapsed_s = 0.0
    stop_reason = "max_cycles"

    import time

    start_time = time.time()

    for cycle in range(1, max_cycles + 1):
        # Check time limit
        if max_simulation_time_s and total_elapsed_s >= max_simulation_time_s:
            stop_reason = "time_limit"
            print(f"\n⏱️ Time limit reached: {total_elapsed_s:.1f} s")
            break

        # Create config for this cycle
        cycle_config = config_with_defaults.copy()

        # Only calibrate capacity at BOL (cycle 1)
        if cycle == 1:
            print(f"\n🔧 Cycle {cycle}: Running with capacity calibration (BOL)")
            cycle_config["skip_capacity_calibration"] = False
        else:
            cycle_config["skip_capacity_calibration"] = True

        # Run single cycle
        cycle_start = time.time()
        result = _run_single_cycle_degradation_internal(
            cell_design=cell_design, simulation_config=cycle_config
        )
        cycle_elapsed = time.time() - cycle_start
        total_elapsed_s += cycle_elapsed

        if not result["success"]:
            print(f"\n✗ Simulation failed at cycle {cycle}: {result.get('error')}")
            stop_reason = "error"
            break

        # Extract degradation data
        deg_sum = result.get("degradation_summary", {})

        # Update cumulative metrics
        cycle_throughput = deg_sum.get("throughput_final_Ah", 0.0)
        total_throughput_Ah += cycle_throughput

        # Calculate energy throughput
        if "timeseries" in result:
            ts = result["timeseries"]
            dt = np.diff(ts["time_s"])
            power_avg = (ts["power_W"][:-1] + ts["power_W"][1:]) / 2
            cycle_energy = np.sum(np.abs(power_avg * dt)) / 3600  # Convert J to Wh
            total_energy_Wh += cycle_energy

        # Calculate SoH
        total_capacity_loss = deg_sum.get("Q_side_reactions_final_Ah", 0.0)
        current_capacity = nominal_capacity_Ah - total_capacity_loss
        current_soh = 100 * (current_capacity / nominal_capacity_Ah)

        # Calculate FCE
        fce = total_throughput_Ah / nominal_capacity_Ah

        # Store cycle data
        cycle_history["cycle_number"].append(cycle)
        cycle_history["soh_pct"].append(current_soh)
        cycle_history["capacity_Ah"].append(current_capacity)
        cycle_history["fce"].append(fce)
        cycle_history["energy_throughput_Wh"].append(total_energy_Wh)
        cycle_history["total_throughput_Ah"].append(total_throughput_Ah)
        cycle_history["LLI_pct"].append(deg_sum.get("LLI_final_pct", 0.0))
        cycle_history["LAM_neg_pct"].append(deg_sum.get("LAM_neg_final_pct", 0.0))
        cycle_history["LAM_pos_pct"].append(deg_sum.get("LAM_pos_final_pct", 0.0))
        cycle_history["Q_SEI_Ah"].append(deg_sum.get("Q_SEI_final_Ah", 0.0))
        cycle_history["Q_SEI_cracks_Ah"].append(
            deg_sum.get("Q_SEI_cracks_final_Ah", 0.0)
        )
        cycle_history["Q_plating_Ah"].append(deg_sum.get("Q_plating_final_Ah", 0.0))
        cycle_history["porosity_neg"].append(deg_sum.get("porosity_neg_final", 0.0))
        cycle_history["porosity_pos"].append(deg_sum.get("porosity_pos_final", 0.0))
        cycle_history["elapsed_time_s"].append(total_elapsed_s)

        # Print progress
        if cycle % save_interval == 0 or current_soh < soh_threshold:
            print(
                f"\nCycle {cycle:4d} | SoH: {current_soh:6.2f}% | "
                f"FCE: {fce:7.1f} | TP: {total_energy_Wh:10.1f} Wh | "
                f"Time: {total_elapsed_s/60:6.1f} min | "
                f"LLI: {deg_sum.get('LLI_final_pct', 0):.4f}%"
            )

        # Check if SoH threshold reached
        if current_soh < soh_threshold:
            print(f"\n{'=' * 80}")
            print(f"✓ SoH threshold reached at cycle {cycle}!")
            print(f"Final SoH: {current_soh:.2f}%")
            print(f"{'=' * 80}")
            stop_reason = "soh_threshold"
            break

    # Create summary
    summary = {
        "total_cycles": cycle,
        "final_soh_pct": current_soh,
        "final_capacity_Ah": current_capacity,
        "nominal_capacity_Ah": nominal_capacity_Ah,
        "capacity_fade_Ah": nominal_capacity_Ah - current_capacity,
        "capacity_fade_pct": 100 - current_soh,
        "total_fce": fce,
        "total_energy_throughput_Wh": total_energy_Wh,
        "total_energy_throughput_kWh": total_energy_Wh / 1000,
        "total_throughput_Ah": total_throughput_Ah,
        "total_simulation_time_s": total_elapsed_s,
        "total_simulation_time_hr": total_elapsed_s / 3600,
        "final_LLI_pct": cycle_history["LLI_pct"][-1],
        "final_LAM_neg_pct": cycle_history["LAM_neg_pct"][-1],
        "final_LAM_pos_pct": cycle_history["LAM_pos_pct"][-1],
        "threshold_reached": current_soh < soh_threshold,
        "stop_reason": stop_reason,
        "degradation_mechanisms": {
            "sei_model": config_with_defaults["sei_model"],
            "lithium_plating": config_with_defaults["lithium_plating"],
            "particle_mechanics": config_with_defaults["particle_mechanics"],
            "sei_on_cracks": config_with_defaults["sei_on_cracks"],
            "loss_of_active_material": config_with_defaults["loss_of_active_material"],
        },
    }

    return {
        "success": True,
        "cycle_history": cycle_history,
        "summary": summary,
        "stop_reason": stop_reason,
    }


def print_drive_cycle_degradation_report(result: dict) -> None:
    """
    Print a formatted report with degradation metrics.

    Args:
        result: Result dictionary from run_drive_cycle_with_degradation()
    """
    if not result.get("success"):
        print(f"Simulation failed: {result.get('error', 'Unknown error')}")
        return

    # Print standard report sections
    from model_library.spmet_drive import print_drive_cycle_report

    print_drive_cycle_report(result)

    # Add degradation section
    if "degradation_summary" in result and result["degradation_summary"]:
        deg = result["degradation_summary"]
        print(f"\n{'─' * 70}")
        print("DEGRADATION ANALYSIS")
        print(f"{'─' * 70}")
        print("\n  Degradation Modes:")
        print(f"    LLI:                 {deg['LLI_final_pct']:.4f}%")
        print(f"    LAM (negative):      {deg['LAM_neg_final_pct']:.4f}%")
        print(f"    LAM (positive):      {deg['LAM_pos_final_pct']:.4f}%")

        print("\n  Capacity Loss Mechanisms:")
        print(f"    SEI:                 {deg['Q_SEI_final_Ah']:.4f} A.h")
        print(f"    SEI on cracks:       {deg['Q_SEI_cracks_final_Ah']:.4f} A.h")
        print(f"    Li plating:          {deg['Q_plating_final_Ah']:.4f} A.h")
        print(f"    All side reactions:  {deg['Q_side_reactions_final_Ah']:.4f} A.h")

        print("\n  Porosity Changes:")
        print(
            f"    Negative electrode:  {deg['porosity_neg_initial']:.4f} → {deg['porosity_neg_final']:.4f} "
            f"(Δ{deg['porosity_neg_change']:.4f})"
        )
        print(
            f"    Positive electrode:  {deg['porosity_pos_initial']:.4f} → {deg['porosity_pos_final']:.4f}"
        )


def print_multi_cycle_summary(result: dict) -> None:
    """
    Print a formatted summary of multi-cycle degradation simulation.

    Args:
        result: Result dictionary from run_multi_cycle_degradation()
    """
    if not result.get("success"):
        print(f"Simulation failed: {result.get('error', 'Unknown error')}")
        return

    summary = result["summary"]

    print("=" * 80)
    print("MULTI-CYCLE DEGRADATION SUMMARY")
    print("=" * 80)
    print(f"\n📊 CYCLE PERFORMANCE")
    print(f"   Total cycles completed: {summary['total_cycles']}")
    print(f"   Stop reason: {summary['stop_reason']}")
    print(f"   Threshold reached: {'Yes' if summary['threshold_reached'] else 'No'}")
    print(f"   Total simulation time: {summary['total_simulation_time_hr']:.2f} hr")

    print(f"\n🔋 STATE OF HEALTH (SoH)")
    print(f"   Initial SoH: 100.00%")
    print(f"   Final SoH: {summary['final_soh_pct']:.2f}%")
    print(f"   Capacity fade: {summary['capacity_fade_pct']:.2f}%")
    print(f"   Initial capacity: {summary['nominal_capacity_Ah']:.2f} Ah")
    print(f"   Final capacity: {summary['final_capacity_Ah']:.2f} Ah")
    print(f"   Capacity lost: {summary['capacity_fade_Ah']:.2f} Ah")

    print(f"\n⚡ FULL CYCLE EQUIVALENT (FCE)")
    print(f"   Total FCE: {summary['total_fce']:.1f} cycles")
    print(f"   (Based on throughput / nominal capacity)")

    print(f"\n🔄 ENERGY THROUGHPUT")
    print(f"   Total energy cycled: {summary['total_energy_throughput_kWh']:.2f} kWh")
    print(f"   Total energy cycled: {summary['total_energy_throughput_Wh']:.0f} Wh")
    print(f"   Charge throughput: {summary['total_throughput_Ah']:.2f} Ah")

    print(f"\n📉 DEGRADATION MECHANISMS")
    print(f"   Loss of Lithium Inventory (LLI): {summary['final_LLI_pct']:.4f}%")
    print(f"   Loss of Active Material (neg): {summary['final_LAM_neg_pct']:.4f}%")
    print(f"   Loss of Active Material (pos): {summary['final_LAM_pos_pct']:.4f}%")

    if summary["capacity_fade_pct"] > 0:
        print(f"\n💡 KEY METRICS")
        print(
            f"   Cycles per 1% SoH loss: {summary['total_cycles'] / summary['capacity_fade_pct']:.1f}"
        )
        print(
            f"   Energy per 1% SoH loss: {summary['total_energy_throughput_kWh'] / summary['capacity_fade_pct']:.2f} kWh"
        )
        print(
            f"   FCE per 1% SoH loss: {summary['total_fce'] / summary['capacity_fade_pct']:.1f}"
        )
        print(
            f"   Time per 1% SoH loss: {summary['total_simulation_time_hr'] / summary['capacity_fade_pct']:.2f} hr"
        )

    print("=" * 80)
