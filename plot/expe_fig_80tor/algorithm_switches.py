#!/usr/bin/env python3

"""
Per-algorithm draw switches.

Edit True/False to control whether each algorithm is shown in figures.
"""

PREFERRED_ORDER = [
    "ocs_eps_global_ksp",
    "pure_ocs_ksp",
    "eps_ecmp",
    "ocs_eps_large_small_10pct",
    "ocs_eps_large_small_20pct",
    "ocs_eps_large_small_30pct",
    "pure_ocs_ksp_greedy",
    "ocs_eps_preset_greedy_10pct",
    "ocs_eps_preset_greedy_20pct",
    "ocs_eps_preset_greedy_30pct",
    "pure_ocs_pruned",
    "ocs_eps_pruned",
    # keep legacy keys for backward compatibility with older logs
    "ocs_eps_large_small",
    "ocs_eps_preset_greedy",
    "ocs_eps_preset_dynamic_greedy",
]

# Default setting:
# - hide pure ECMP
# - keep 5 algorithms enabled for now
ALGORITHM_ENABLED = {
    "ocs_eps_global_ksp": True,
    "pure_ocs_ksp": True,
    "eps_ecmp": False,
    "ocs_eps_large_small_10pct": False,
    "ocs_eps_large_small_20pct": False,
    "ocs_eps_large_small_30pct": False,
    "pure_ocs_ksp_greedy": True,
    "ocs_eps_preset_greedy_10pct": False,
    "ocs_eps_preset_greedy_20pct": False,
    "ocs_eps_preset_greedy_30pct": False,
    "ocs_eps_preset_dynamic_greedy": True,
    "pure_ocs_pruned": False,
    "ocs_eps_pruned": False,
    # legacy toggles
    "ocs_eps_large_small": True,
    "ocs_eps_preset_greedy": False,
}

ALGORITHM_LABELS = {
    "ocs_eps_global_ksp": "Hybrid-ksp",
    "pure_ocs_ksp": "Optics-ksp",
    "eps_ecmp": "Electronics-Ksp",
    "ocs_eps_large_small_10pct": "Helios-10%",
    "ocs_eps_large_small_20pct": "Helios-20%",
    "ocs_eps_large_small_30pct": "Helios-30%",
    "pure_ocs_ksp_greedy": "Optics-greedy",
    "ocs_eps_preset_greedy_10pct": "Hybrid-greedy-10%",
    "ocs_eps_preset_greedy_20pct": "Hybrid-greedy-20%",
    "ocs_eps_preset_greedy_30pct": "Hybrid-greedy-30%",
    "ocs_eps_preset_dynamic_greedy": "Hyacinth",
    "pure_ocs_pruned": "Optics-pruned",
    "ocs_eps_pruned": "Hybrid-pruned",
    # legacy labels
    "ocs_eps_large_small": "Helios-20%",
    "ocs_eps_preset_greedy": "Hybrid-greedy-20%",
}

ALGORITHM_COLORS = {
    "ocs_eps_global_ksp": "#4E79A7",
    "pure_ocs_ksp": "#F28E2B",
    "eps_ecmp": "#FFBE7D",
    "ocs_eps_pruned": "#FF9900",
    "ocs_eps_large_small_10pct": "#FF7B72",
    "ocs_eps_large_small_20pct": "#F9413D",
    "ocs_eps_large_small_30pct": "#C92A2A",
    "pure_ocs_ksp_greedy": "#76B7B2",
    "ocs_eps_preset_greedy_10pct": "#6DA8FF",
    "ocs_eps_preset_greedy_20pct": "#3071F4",
    "ocs_eps_preset_greedy_30pct": "#1E4FB8",
    "ocs_eps_preset_dynamic_greedy": "#000000",
    "pure_ocs_pruned": "#3DB19E",
    # legacy colors
    "ocs_eps_large_small": "#F9413D",
    "ocs_eps_preset_greedy": "#3071F4",
}


def enabled_algorithms() -> list[str]:
    return [a for a in PREFERRED_ORDER if ALGORITHM_ENABLED.get(a, False)]
