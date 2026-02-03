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

    Runs ONE FLAT SIMULATION with repeated drive cycles until:
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
            - Multi-cycle mode options:
                - max_cycles: Number of cycle repetitions to simulate (int, default: 1)
                - soh_threshold: Stop if SoH falls below this % (float, default: 80.0)
                - max_simulation_time_s: Stop if total sim time exceeds limit (float, optional)
                - save_interval: Sample interval for cycle history (int, default: 10)

    Returns:
        Dictionary containing:
            - cycle_history: DataFrame with per-cycle metrics (sampled at save_interval)
            - summary: Dict with final multi-cycle metrics
            - config: Simulation configuration used
            - stop_reason: 'soh_threshold', 'max_cycles', 'time_limit', or 'completed'
    """
    nominal_capacity_Ah = cell_design["nominal_capacity"]["value"]

    # Extract control parameters
    max_cycles = simulation_config.get("max_cycles", 1)
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
