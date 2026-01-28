"""
Cell Capacity Module

Calculate cell capacity from cell design manifest data.
Provides both direct KPI lookup and first-principles calculation from electrode design.
"""


def get_cell_capacity(cell_design: dict) -> dict:
    """
    Get cell capacity from cell design manifest.

    This function calculates capacity using two approaches:
    1. Direct lookup from KPIs (nominal_capacity)
    2. First-principles calculation from electrode design parameters

    Args:
        cell_design: Cell design dictionary.

    Returns:
        Dictionary containing:
            - calculated_capacity_Ah: Capacity calculated from electrode design [Ah]
            - positive_electrode_capacity_Ah: Positive electrode theoretical capacity [Ah]
            - negative_electrode_capacity_Ah: Negative electrode theoretical capacity [Ah]
            - limiting_electrode: Which electrode limits capacity ("positive" or "negative")
            - np_ratio: N/P ratio (negative/positive capacity ratio)
    """
    capacities = {}
    jelly_roll = cell_design.get("jelly_roll", {})
    jelly_roll_count = jelly_roll.get("count", {}).get("value", 1)

    for elec_type in ["positive_electrode", "negative_electrode"]:
        electrode = cell_design.get(elec_type, {})
        if not electrode:
            capacities[elec_type] = 0.0
            continue

        coating = electrode.get("coating", {})
        if not coating:
            capacities[elec_type] = 0.0
            continue

        formulation = coating.get("formulation", {})
        mass_loading_mg_cm2 = coating.get("mass_loading", {}).get("value", 0.0)
        num_coated_sides = coating.get("count", {}).get("value", 1)

        # Get specific capacity (mAh/g)
        specific_capacity_mAh_g = 0.0
        for key in formulation:
            if "active_material" in key and not key.endswith("_mass_fraction"):
                mass_fraction_key = f"{key}_mass_fraction"
                mass_fraction = formulation.get(mass_fraction_key, {}).get("value", 0.0)
                specific_capacity = formulation[key].get("specific_capacity", {}).get("value", 0.0)
                specific_capacity_mAh_g += specific_capacity * mass_fraction

        # Electrode dimensions and count
        width = electrode.get("width", {}).get("value", 0.0)
        height = electrode.get("height", {}).get("value", 0.0)
        electrode_area_cm2 = (width / 10.0) * (height / 10.0)
        electrode_count = electrode.get("count", {}).get("value", 1)

        # Calculate capacity in Ah
        capacity_mAh = (
            mass_loading_mg_cm2
            * specific_capacity_mAh_g
            * electrode_area_cm2
            * electrode_count
            * jelly_roll_count
            * num_coated_sides
            / 1000.0  # mg to g
        )
        capacities[elec_type] = capacity_mAh / 1000.0  # mAh to Ah

    pos_capacity_Ah = capacities["positive_electrode"]
    neg_capacity_Ah = capacities["negative_electrode"]

    # Limiting electrode determines cell capacity
    if pos_capacity_Ah <= neg_capacity_Ah:
        limiting_electrode = "positive"
        calculated_capacity_Ah = pos_capacity_Ah
    else:
        limiting_electrode = "negative"
        calculated_capacity_Ah = neg_capacity_Ah

    # N/P ratio
    np_ratio = neg_capacity_Ah / pos_capacity_Ah if pos_capacity_Ah > 0 else 0.0

    return {
        "calculated_capacity_Ah": calculated_capacity_Ah,
        "positive_electrode_capacity_Ah": pos_capacity_Ah,
        "negative_electrode_capacity_Ah": neg_capacity_Ah,
        "limiting_electrode": limiting_electrode,
        "np_ratio": np_ratio,
    }
