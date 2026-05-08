#!/usr/bin/env python3

"""
Per-algorithm draw switches.

Edit True/False to control whether each algorithm is shown in figures.
"""

PREFERRED_ORDER = [
    "ocs_eps_global_ksp",
    "pure_ocs_ksp",
    "eps_ecmp",
    "ocs_eps_large_small",
    "pure_ocs_ksp_greedy",
    "ocs_eps_preset_greedy",
    "pure_ocs_3hop_preset",
    "pure_ocs_pruned",
    "ocs_eps_pruned",
    "ocs_eps_preset_dynamic_greedy",
]

# Default setting:
# - hide pure ECMP
# - keep 5 algorithms enabled for now
ALGORITHM_ENABLED = {
    "ocs_eps_global_ksp": True,
    "pure_ocs_ksp": True,
    "eps_ecmp": False,
    "ocs_eps_large_small": True,
    "pure_ocs_ksp_greedy": True,
    "ocs_eps_preset_greedy": True,
    "ocs_eps_preset_dynamic_greedy": True,
    "pure_ocs_3hop_preset": False,
    "pure_ocs_pruned": False,
    "ocs_eps_pruned": False,
}

ALGORITHM_LABELS = {
    "ocs_eps_global_ksp": "alo.5",
    "pure_ocs_ksp": "alo.6",
    "eps_ecmp": "alo.7",
    "ocs_eps_large_small": "alo.1",
    "pure_ocs_ksp_greedy": "alo.8",
    "ocs_eps_preset_greedy": "alo.2",
    "ocs_eps_preset_dynamic_greedy": "Hyacinth",
    "pure_ocs_3hop_preset": "alo.9",
    "pure_ocs_pruned": "alo.3",
    "ocs_eps_pruned": "alo.4",
}

ALGORITHM_COLORS = {
    "ocs_eps_global_ksp": "#4E79A7",
    "pure_ocs_ksp": "#F28E2B",
    "eps_ecmp": "#FFBE7D",
    "ocs_eps_pruned": "#FF9900",
    "ocs_eps_large_small": "#F9413D",
    "pure_ocs_ksp_greedy": "#76B7B2",
    "ocs_eps_preset_greedy": "#3071F4",
    "ocs_eps_preset_dynamic_greedy": "#000000",
    "pure_ocs_3hop_preset": "#EDC948",
    "pure_ocs_pruned": "#3DB19E",
}


def enabled_algorithms() -> list[str]:
    return [a for a in PREFERRED_ORDER if ALGORITHM_ENABLED.get(a, False)]
