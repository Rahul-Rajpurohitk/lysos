"""list_elements — supported element palette (37 entries).

Tells the agent which elements are accepted by edit_molecule. Each
entry has symbol, atomic number, common valences, full name, group.
"""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel

from ..base import tool


class ListElementsInput(BaseModel):
    pass


_PALETTE: List[Dict[str, Any]] = [
    {"sym": "H",  "Z": 1,  "valences": [1],     "name": "Hydrogen",  "group": "nonmetal"},
    {"sym": "Li", "Z": 3,  "valences": [1],     "name": "Lithium",   "group": "alkali"},
    {"sym": "Be", "Z": 4,  "valences": [2],     "name": "Beryllium", "group": "alkaline-earth"},
    {"sym": "B",  "Z": 5,  "valences": [3],     "name": "Boron",     "group": "metalloid"},
    {"sym": "C",  "Z": 6,  "valences": [4],     "name": "Carbon",    "group": "nonmetal"},
    {"sym": "N",  "Z": 7,  "valences": [3, 5],  "name": "Nitrogen",  "group": "nonmetal"},
    {"sym": "O",  "Z": 8,  "valences": [2],     "name": "Oxygen",    "group": "nonmetal"},
    {"sym": "F",  "Z": 9,  "valences": [1],     "name": "Fluorine",  "group": "halogen"},
    {"sym": "Na", "Z": 11, "valences": [1],     "name": "Sodium",    "group": "alkali"},
    {"sym": "Mg", "Z": 12, "valences": [2],     "name": "Magnesium", "group": "alkaline-earth"},
    {"sym": "Al", "Z": 13, "valences": [3],     "name": "Aluminum",  "group": "post-transition"},
    {"sym": "Si", "Z": 14, "valences": [4],     "name": "Silicon",   "group": "metalloid"},
    {"sym": "P",  "Z": 15, "valences": [3, 5],  "name": "Phosphorus","group": "nonmetal"},
    {"sym": "S",  "Z": 16, "valences": [2, 4, 6], "name": "Sulfur",  "group": "nonmetal"},
    {"sym": "Cl", "Z": 17, "valences": [1, 3, 5, 7], "name": "Chlorine", "group": "halogen"},
    {"sym": "K",  "Z": 19, "valences": [1],     "name": "Potassium", "group": "alkali"},
    {"sym": "Ca", "Z": 20, "valences": [2],     "name": "Calcium",   "group": "alkaline-earth"},
    {"sym": "Ti", "Z": 22, "valences": [4],     "name": "Titanium",  "group": "transition"},
    {"sym": "V",  "Z": 23, "valences": [3, 5],  "name": "Vanadium",  "group": "transition"},
    {"sym": "Cr", "Z": 24, "valences": [3, 6],  "name": "Chromium",  "group": "transition"},
    {"sym": "Mn", "Z": 25, "valences": [2, 4, 7], "name": "Manganese","group": "transition"},
    {"sym": "Fe", "Z": 26, "valences": [2, 3],  "name": "Iron",      "group": "transition"},
    {"sym": "Co", "Z": 27, "valences": [2, 3],  "name": "Cobalt",    "group": "transition"},
    {"sym": "Ni", "Z": 28, "valences": [2],     "name": "Nickel",    "group": "transition"},
    {"sym": "Cu", "Z": 29, "valences": [1, 2],  "name": "Copper",    "group": "transition"},
    {"sym": "Zn", "Z": 30, "valences": [2],     "name": "Zinc",      "group": "transition"},
    {"sym": "As", "Z": 33, "valences": [3, 5],  "name": "Arsenic",   "group": "metalloid"},
    {"sym": "Se", "Z": 34, "valences": [2, 4, 6], "name": "Selenium","group": "nonmetal"},
    {"sym": "Br", "Z": 35, "valences": [1, 3, 5], "name": "Bromine", "group": "halogen"},
    {"sym": "Mo", "Z": 42, "valences": [4, 6],  "name": "Molybdenum","group": "transition"},
    {"sym": "Ru", "Z": 44, "valences": [2, 3],  "name": "Ruthenium", "group": "transition"},
    {"sym": "Pd", "Z": 46, "valences": [2],     "name": "Palladium", "group": "transition"},
    {"sym": "Ag", "Z": 47, "valences": [1],     "name": "Silver",    "group": "transition"},
    {"sym": "I",  "Z": 53, "valences": [1, 3, 5, 7], "name": "Iodine","group": "halogen"},
    {"sym": "Pt", "Z": 78, "valences": [2, 4],  "name": "Platinum",  "group": "transition"},
    {"sym": "Au", "Z": 79, "valences": [1, 3],  "name": "Gold",      "group": "transition"},
    {"sym": "Hg", "Z": 80, "valences": [1, 2],  "name": "Mercury",   "group": "transition"},
]


@tool(
    name="list_elements",
    description=(
        "List the supported element palette (37 entries) the agent can "
        "use in edit_molecule swap_element / add_atom_at. Each entry: "
        "symbol, atomic number, common valences, full name, group."
    ),
    category="chem_workbench",
    input_model=ListElementsInput,
    expected_duration_ms=1,
    tags=("chemistry", "elements", "reference"),
)
def list_elements() -> Dict[str, Any]:
    return {"elements": _PALETTE, "count": len(_PALETTE)}
