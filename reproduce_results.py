from __future__ import annotations

"""
Reproducibility driver for the THA vs ORIF Markov model.

Running this script regenerates the manuscript-facing CSV tables, internal
validation checks, state map, and deterministic sensitivity-analysis figures.
Sensitivity analyses use 10-year incremental net monetary benefit (INMB) at a
willingness-to-pay threshold of $50,000/QALY. Positive INMB favors acute THA;
negative INMB favors ORIF.
"""

import importlib.util
import math
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial"]
from matplotlib.colors import ListedColormap
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
ORIGINAL_PATH = BASE_DIR / "parameters.py"
PATCHED_PATH = BASE_DIR / "model.py"

if not ORIGINAL_PATH.exists():
    raise FileNotFoundError(f"Required source file not found: {ORIGINAL_PATH}")
if not PATCHED_PATH.exists():
    raise FileNotFoundError(f"Required model implementation file not found: {PATCHED_PATH}")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


original = _load_module("parameters", ORIGINAL_PATH)
reviewer_patched = _load_module("reviewer_patched_runtime", PATCHED_PATH)

ModelConfig = reviewer_patched.ModelConfig
THA_ORIF_Markov = reviewer_patched.THA_ORIF_Markov
STATE_IDX = reviewer_patched.STATE_IDX
COST = reviewer_patched.COST
UTIL = reviewer_patched.UTIL
annual_to_per_cycle = reviewer_patched.annual_to_per_cycle

WTP = 50_000.0
DEFAULT_COHORT = 1000
HORIZON_LABELS: List[Tuple[float, str]] = [
    (0.25, "90 days"),
    (1.0, "1 year"),
    (2.0, "2 years"),
    (5.0, "5 years"),
    (10.0, "10 years"),
]


@contextmanager
def temporary_dict_updates(target: Dict, updates: Dict):
    original_values = {k: target[k] for k in updates}
    try:
        target.update(updates)
        yield
    finally:
        target.update(original_values)


@contextmanager
def temporary_attr_updates(obj, updates: Dict):
    original_values = {k: getattr(obj, k) for k in updates}
    try:
        for key, value in updates.items():
            setattr(obj, key, value)
        yield
    finally:
        for key, value in original_values.items():
            setattr(obj, key, value)


# ----------------------------- core outputs -----------------------------

def simulate_arm(cfg: ModelConfig, arm: str, n_cohort: int = DEFAULT_COHORT, return_trace: bool = True):
    model = THA_ORIF_Markov(cfg)
    return model.simulate(n_cohort=n_cohort, arm=arm, return_trace=return_trace)


def run_base_case_outputs(n_cohort: int = DEFAULT_COHORT):
    outputs = []
    for horizon_years, label in HORIZON_LABELS:
        cfg = ModelConfig()
        cfg.horizon_years = horizon_years
        for arm in ["THA", "ORIF"]:
            df, counts, total_cost, total_qaly, trace = simulate_arm(cfg, arm, n_cohort=n_cohort, return_trace=True)
            outputs.append({
                "Time Horizon": label,
                "Arm": arm,
                "end_states": df,
                "counts": counts,
                "total_cost": total_cost,
                "total_qaly": total_qaly,
                "trace": trace,
            })
    return outputs


def summarize_outputs(outputs: List[Dict], n_cohort: int = DEFAULT_COHORT):
    summary_rows = []
    event_rows = []
    cost_rows = []
    qaly_rows = []

    for row in outputs:
        label = row["Time Horizon"]
        arm = row["Arm"]
        end_states = row["end_states"]
        counts = row["counts"]
        total_cost = row["total_cost"]
        total_qaly = row["total_qaly"]

        stable_well_count = 0.0
        if arm == "THA":
            stable_well_count = float(end_states.loc[end_states["state"] == "WELL_THA", "count"].iloc[0])
        else:
            stable_well_count = float(end_states.loc[end_states["state"] == "WELL_ORIF", "count"].iloc[0])

        death_count = float(end_states.loc[end_states["state"] == "DEATH", "count"].iloc[0])

        summary_rows.append({
            "Time Horizon": label,
            "Arm": arm,
            "Stable well state (n)": stable_well_count,
            "Stable well state (%)": 100.0 * stable_well_count / n_cohort,
            "Death (n)": death_count,
            "Death (%)": 100.0 * death_count / n_cohort,
            "Total cost (USD)": total_cost,
            "Per-patient cost (USD)": total_cost / n_cohort,
            "Total QALYs": total_qaly,
            "Per-patient QALYs": total_qaly / n_cohort,
            "Medical complications": counts["medical_comps"],
            "Infection-related events": counts["infection_events"],
            "Dislocation events": counts["dislocations"],
            "Revision events": counts["revisions"],
            "Conversion THA": counts["conversions"],
            "ORIF reoperations": counts["orif_reops"],
            "Refracture/periprosthetic fracture events": counts["refractures"],
        })

    summary_df = pd.DataFrame(summary_rows)

    for label, group in summary_df.groupby("Time Horizon", sort=False):
        tha = group[group["Arm"] == "THA"].iloc[0]
        orif = group[group["Arm"] == "ORIF"].iloc[0]
        for event_name in [
            "Stable well state (n)",
            "Death (n)",
            "Medical complications",
            "Infection-related events",
            "Dislocation events",
            "Revision events",
            "Conversion THA",
            "ORIF reoperations",
            "Refracture/periprosthetic fracture events",
        ]:
            event_rows.append({
                "Time Horizon": label,
                "Event / State": event_name.replace(" (n)", ""),
                "THA (n)": tha[event_name],
                "THA (%)": 100.0 * tha[event_name] / n_cohort,
                "ORIF (n)": orif[event_name],
                "ORIF (%)": 100.0 * orif[event_name] / n_cohort,
            })

        cost_rows.append({
            "Time Horizon": label,
            "THA total cost (USD)": tha["Total cost (USD)"],
            "ORIF total cost (USD)": orif["Total cost (USD)"],
            "Δ Cost (ORIF - THA)": orif["Total cost (USD)"] - tha["Total cost (USD)"],
            "THA per-patient cost (USD)": tha["Per-patient cost (USD)"],
            "ORIF per-patient cost (USD)": orif["Per-patient cost (USD)"],
        })

        qaly_rows.append({
            "Time Horizon": label,
            "THA total QALYs": tha["Total QALYs"],
            "ORIF total QALYs": orif["Total QALYs"],
            "Δ QALYs (THA - ORIF)": tha["Total QALYs"] - orif["Total QALYs"],
            "THA per-patient QALYs": tha["Per-patient QALYs"],
            "ORIF per-patient QALYs": orif["Per-patient QALYs"],
        })

    return summary_df, pd.DataFrame(event_rows), pd.DataFrame(cost_rows), pd.DataFrame(qaly_rows)


def compute_incremental_outputs(cfg: ModelConfig, n_cohort: int = DEFAULT_COHORT) -> Dict[str, float]:
    _, _, cost_tha, qaly_tha, _ = simulate_arm(cfg, "THA", n_cohort=n_cohort, return_trace=True)
    _, _, cost_orif, qaly_orif, _ = simulate_arm(cfg, "ORIF", n_cohort=n_cohort, return_trace=True)
    delta_cost = cost_tha - cost_orif
    delta_qaly = qaly_tha - qaly_orif
    inmb = (delta_qaly * WTP) - delta_cost
    return {
        "cost_tha": cost_tha,
        "cost_orif": cost_orif,
        "qaly_tha": qaly_tha,
        "qaly_orif": qaly_orif,
        "delta_cost": delta_cost,
        "delta_qaly": delta_qaly,
        "inmb": inmb,
    }


# ----------------------------- validation suite -----------------------------

def run_final_validation_suite(n_cohort: int = DEFAULT_COHORT) -> pd.DataFrame:
    rows = []

    # Base-case cohort integrity checks
    cfg = ModelConfig()
    model = THA_ORIF_Markov(cfg)
    for arm in ["THA", "ORIF"]:
        _, _, _, _, trace = model.simulate(n_cohort=n_cohort, arm=arm, return_trace=True)
        cycle_totals = trace.sum(axis=1)
        death_series = trace[:, STATE_IDX["DEATH"]]
        rows.append({
            "test_group": "base_case",
            "test_name": f"{arm}_cohort_conservation",
            "passed": bool(np.all(np.abs(cycle_totals - n_cohort) < 1e-9)),
            "value": float(np.max(np.abs(cycle_totals - n_cohort))),
            "expected": 0.0,
            "details": "Maximum absolute deviation from starting cohort across cycles",
        })
        rows.append({
            "test_group": "base_case",
            "test_name": f"{arm}_death_absorbing",
            "passed": bool(np.all(np.diff(death_series) >= -1e-9)),
            "value": float(np.min(np.diff(death_series))) if len(death_series) > 1 else 0.0,
            "expected": "non-decreasing",
            "details": "Death-state occupancy should never decline",
        })
        rows.append({
            "test_group": "base_case",
            "test_name": f"{arm}_no_negative_states",
            "passed": bool(np.min(trace) >= -1e-9),
            "value": float(np.min(trace)),
            "expected": ">= 0",
            "details": "All state occupancies should remain non-negative",
        })

    # Zero-event stability
    cfg0 = ModelConfig()
    for attr in ["dislocation_primary", "pji_primary", "revision_primary", "orif_conversion", "orif_dislocation", "orif_ssi", "orif_reop"]:
        sched = getattr(cfg0, attr)
        if hasattr(sched, "by_cycle"):
            sched.by_cycle = {k: 0.0 for k in sched.by_cycle}
            sched.taper_after_24mo = 0.0
    cfg0.med_comp_tha_1y = 0.0
    cfg0.med_comp_orif_90d = 0.0
    cfg0.orif_refracture_1y = 0.0
    cfg0.orif_30d_mortality = 0.0
    cfg0.orif_1y_mortality = 0.0
    cfg0.tha_30d_mortality = 0.0
    cfg0.tha_3mo_mortality = 0.0
    cfg0.tha_1y_mortality = 0.0
    cfg0.orif_reop_30d_mortality = 0.0
    cfg0.age_mortality.per_cycle = lambda cycle_idx: 0.0
    model0 = THA_ORIF_Markov(cfg0)
    for arm, state in [("THA", "WELL_THA"), ("ORIF", "WELL_ORIF")]:
        df, _, _, _, _ = model0.simulate(n_cohort=n_cohort, arm=arm, return_trace=True)
        final_main = float(df.loc[df["state"] == state, "count"].iloc[0])
        final_death = float(df.loc[df["state"] == "DEATH", "count"].iloc[0])
        rows.append({
            "test_group": "edge_case",
            "test_name": f"{arm}_zero_event_stability",
            "passed": bool(abs(final_main - n_cohort) < 1e-9 and abs(final_death) < 1e-9),
            "value": final_main,
            "expected": n_cohort,
            "details": "With all hazards removed, the cohort should remain entirely in the initial well state",
        })

    # Quarter-1 schedule benchmarks
    cfg1 = ModelConfig()
    cfg1.horizon_years = 0.25
    cfg1.age_mortality.per_cycle = lambda cycle_idx: 0.0
    cfg1.orif_30d_mortality = 0.0
    cfg1.orif_1y_mortality = 0.0
    cfg1.tha_30d_mortality = 0.0
    cfg1.tha_3mo_mortality = 0.0
    cfg1.tha_1y_mortality = 0.0
    cfg1.orif_reop_30d_mortality = 0.0
    model1 = THA_ORIF_Markov(cfg1)
    _, c_tha, *_ = model1.simulate(n_cohort=n_cohort, arm="THA", return_trace=False)
    _, c_orif, *_ = model1.simulate(n_cohort=n_cohort, arm="ORIF", return_trace=False)
    benchmark_rows = [
        ("THA_Q1_dislocation_events", c_tha["dislocations"], n_cohort * cfg1.dislocation_primary.get(0), "Q1 THA dislocation events should match the programmed quarter-1 schedule when mortality is zero"),
        ("THA_Q1_pji_events", c_tha["pji"], n_cohort * cfg1.pji_primary.get(0), "Q1 THA infection events should match the programmed quarter-1 schedule when mortality is zero"),
        ("ORIF_Q1_ssi_events", c_orif["pji"], n_cohort * cfg1.orif_ssi.get(0), "Q1 ORIF SSI events should match the programmed quarter-1 schedule when mortality is zero"),
        ("ORIF_Q1_medical_comp_events", c_orif["medical_comps"], n_cohort * cfg1.med_comp_orif_90d, "Q1 ORIF medical-complication events should match the programmed 90-day risk when mortality is zero"),
    ]
    for name, observed, expected, details in benchmark_rows:
        rows.append({
            "test_group": "benchmark",
            "test_name": name,
            "passed": bool(abs(observed - expected) < 1e-6),
            "value": float(observed),
            "expected": float(expected),
            "details": details,
        })

    # ORIF SSI isolation
    cfg_ssi = ModelConfig()
    cfg_ssi.horizon_years = 1.0
    cfg_ssi.age_mortality.per_cycle = lambda cycle_idx: 0.0
    cfg_ssi.orif_30d_mortality = 0.0
    cfg_ssi.orif_1y_mortality = 0.0
    cfg_ssi.orif_reop_30d_mortality = 0.0
    cfg_ssi.med_comp_orif_90d = 0.0
    cfg_ssi.med_comp_tha_1y = 0.0
    cfg_ssi.orif_refracture_1y = 0.0
    for attr in ["orif_conversion", "orif_dislocation", "orif_reop", "dislocation_primary", "pji_primary", "revision_primary"]:
        sched = getattr(cfg_ssi, attr)
        if hasattr(sched, "by_cycle"):
            sched.by_cycle = {k: 0.0 for k in sched.by_cycle}
            sched.taper_after_24mo = 0.0
    df_ssi, _, _, _, _ = THA_ORIF_Markov(cfg_ssi).simulate(n_cohort=n_cohort, arm="ORIF", return_trace=True)
    tha_leak_states = [
        "WELL_THA", "DISLOCATION", "PJI_EARLY", "PJI_LATE", "CONVERSION_THA",
        "REV_TUNNEL_ASEPTIC", "REV_TUNNEL_SEPTIC", "POST_REV_ASEPTIC", "POST_REV_SEPTIC",
        "WELL_REVISED", "ASEPTIC_LOOSENING",
    ]
    max_leak = float(df_ssi[df_ssi["state"].isin(tha_leak_states)]["count"].max())
    rows.append({
        "test_group": "pathway_isolation",
        "test_name": "ORIF_SSI_no_THA_state_leakage",
        "passed": bool(abs(max_leak) < 1e-9),
        "value": max_leak,
        "expected": 0.0,
        "details": "Under isolated ORIF SSI stress testing, no THA-specific states should accrue occupancy",
    })

    # Converted THA should not receive index THA medical-complication schedule in the ORIF arm
    cfg_conv = ModelConfig()
    cfg_conv.horizon_years = 1.0
    cfg_conv.age_mortality.per_cycle = lambda cycle_idx: 0.0
    cfg_conv.orif_30d_mortality = 0.0
    cfg_conv.orif_1y_mortality = 0.0
    cfg_conv.orif_reop_30d_mortality = 0.0
    cfg_conv.tha_30d_mortality = 0.0
    cfg_conv.tha_3mo_mortality = 0.0
    cfg_conv.tha_1y_mortality = 0.0
    cfg_conv.med_comp_orif_90d = 0.0
    cfg_conv.med_comp_tha_1y = 1.0  # intentionally extreme if incorrectly applied to converted THA patients
    cfg_conv.orif_refracture_1y = 0.0
    for attr in ["orif_dislocation", "orif_ssi", "orif_reop", "dislocation_primary", "pji_primary", "revision_primary"]:
        sched = getattr(cfg_conv, attr)
        if hasattr(sched, "by_cycle"):
            sched.by_cycle = {k: 0.0 for k in sched.by_cycle}
            sched.taper_after_24mo = 0.0
    cfg_conv.orif_conversion.by_cycle = {0: 0.5}
    cfg_conv.orif_conversion.taper_after_24mo = 0.0
    _, counts_conv, _, _, _ = THA_ORIF_Markov(cfg_conv).simulate(n_cohort=n_cohort, arm="ORIF", return_trace=True)
    rows.append({
        "test_group": "pathway_isolation",
        "test_name": "converted_THA_no_index_THA_medical_comp_schedule",
        "passed": bool(abs(counts_conv["medical_comps"]) < 1e-9),
        "value": float(counts_conv["medical_comps"]),
        "expected": 0.0,
        "details": "In a conversion-only stress test, converted THA patients should not accrue index-THA medical-complication events",
    })

    # Refracture-to-reoperation accounting
    cfg_r = ModelConfig()
    cfg_r.horizon_years = 1.25
    cfg_r.orif_refracture_1y = 0.10
    cfg_r.age_mortality.per_cycle = lambda cycle_idx: 0.0
    cfg_r.orif_30d_mortality = 0.0
    cfg_r.orif_1y_mortality = 0.0
    cfg_r.orif_reop_30d_mortality = 0.0
    cfg_r.med_comp_orif_90d = 0.0
    for attr in ["orif_conversion", "orif_dislocation", "orif_ssi", "orif_reop"]:
        sched = getattr(cfg_r, attr)
        if hasattr(sched, "by_cycle"):
            sched.by_cycle = {k: 0.0 for k in sched.by_cycle}
            sched.taper_after_24mo = 0.0
    _, counts_r, _, _, _ = THA_ORIF_Markov(cfg_r).simulate(n_cohort=n_cohort, arm="ORIF", return_trace=True)
    rows.append({
        "test_group": "benchmark",
        "test_name": "ORIF_refracture_to_reop_accounting",
        "passed": bool(abs(counts_r["orif_reops"] - counts_r["refractures"]) < 1e-6),
        "value": float(counts_r["orif_reops"]),
        "expected": float(counts_r["refractures"]),
        "details": "Under isolated refracture-only conditions, each refracture should generate one ORIF reoperation event",
    })

    return pd.DataFrame(rows)


# ----------------------------- sensitivity analysis -----------------------------

def _scenario_inmb(modifier: Callable[[ModelConfig], None], *, util_updates: Dict | None = None, cost_updates: Dict | None = None) -> float:
    cfg = ModelConfig()
    cfg.horizon_years = 10.0
    modifier(cfg)
    util_updates = util_updates or {}
    cost_updates = cost_updates or {}
    with temporary_dict_updates(UTIL, util_updates), temporary_dict_updates(COST, cost_updates):
        return compute_incremental_outputs(cfg)["inmb"]


def one_way_sensitivity_data() -> pd.DataFrame:
    base_cfg = ModelConfig()
    base_cfg.horizon_years = 10.0
    base_inmb = compute_incremental_outputs(base_cfg)["inmb"]

    params = [
        {
            "label": "ORIF 1-year mortality",
            "low": lambda cfg: setattr(cfg, "orif_1y_mortality", 0.15),
            "high": lambda cfg: setattr(cfg, "orif_1y_mortality", 0.26),
        },
        {
            "label": "ORIF index cost",
            "low": lambda cfg: None,
            "high": lambda cfg: None,
            "low_cost": {"INDEX_ORIF": 30_000.0},
            "high_cost": {"INDEX_ORIF": 60_000.0},
        },
        {
            "label": "ORIF well-state utility",
            "low": lambda cfg: None,
            "high": lambda cfg: None,
            "low_util": {"WELL_ORIF": 0.60},
            "high_util": {"WELL_ORIF": 0.85},
        },
        {
            "label": "THA index cost",
            "low": lambda cfg: None,
            "high": lambda cfg: None,
            "low_cost": {"INDEX_THA": 30_000.0},
            "high_cost": {"INDEX_THA": 70_000.0},
        },
        {
            "label": "THA 1-year mortality",
            "low": lambda cfg: setattr(cfg, "tha_1y_mortality", 0.10),
            "high": lambda cfg: setattr(cfg, "tha_1y_mortality", 0.187),
        },
        {
            "label": "ORIF medical-complication risk",
            "low": lambda cfg: setattr(cfg, "med_comp_orif_90d", 0.20),
            "high": lambda cfg: setattr(cfg, "med_comp_orif_90d", 0.50),
        },
        {
            "label": "Medical-complication cost",
            "low": lambda cfg: None,
            "high": lambda cfg: None,
            "low_cost": {"MEDICAL_COMP_EP": 5_000.0},
            "high_cost": {"MEDICAL_COMP_EP": 25_000.0},
        },
    ]

    rows = []
    for param in params:
        low_val = _scenario_inmb(
            param["low"],
            util_updates=param.get("low_util"),
            cost_updates=param.get("low_cost"),
        )
        high_val = _scenario_inmb(
            param["high"],
            util_updates=param.get("high_util"),
            cost_updates=param.get("high_cost"),
        )
        rows.append({
            "parameter": param["label"],
            "low_inmb": low_val,
            "high_inmb": high_val,
            "base_inmb": base_inmb,
            "range_width": abs(high_val - low_val),
        })

    return pd.DataFrame(rows).sort_values("range_width", ascending=False).reset_index(drop=True)


def utility_grid(n: int = 41) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[float, float]]:
    orif_vals = np.linspace(0.20, 0.90, n)
    tha_vals = np.linspace(0.20, 0.90, n)
    z = np.zeros((n, n), dtype=float)
    base = (UTIL["WELL_ORIF"], UTIL["WELL_THA"])

    for i, tha_u in enumerate(tha_vals):
        for j, orif_u in enumerate(orif_vals):
            with temporary_dict_updates(UTIL, {"WELL_ORIF": float(orif_u), "WELL_THA": float(tha_u)}):
                cfg = ModelConfig()
                cfg.horizon_years = 10.0
                z[i, j] = compute_incremental_outputs(cfg)["inmb"]

    return orif_vals, tha_vals, z, base


def cost_grid(n: int = 41) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[float, float]]:
    orif_costs = np.linspace(8_000.0, 60_000.0, n)
    tha_costs = np.linspace(8_000.0, 70_000.0, n)
    z = np.zeros((n, n), dtype=float)
    base = (COST["INDEX_ORIF"], COST["INDEX_THA"])

    for i, tha_cost in enumerate(tha_costs):
        for j, orif_cost in enumerate(orif_costs):
            with temporary_dict_updates(COST, {"INDEX_ORIF": float(orif_cost), "INDEX_THA": float(tha_cost)}):
                cfg = ModelConfig()
                cfg.horizon_years = 10.0
                z[i, j] = compute_incremental_outputs(cfg)["inmb"]

    return orif_costs, tha_costs, z, base


# ----------------------------- figure generation -----------------------------

def make_one_way_figure(out_path: Path):
    df = one_way_sensitivity_data()
    base_inmb = float(df["base_inmb"].iloc[0])

    plt.close("all")
    fig, ax = plt.subplots(figsize=(12, 7.5))
    y_positions = np.arange(len(df))

    for y, (_, row) in zip(y_positions, df.iterrows()):
        low = min(row["low_inmb"], row["high_inmb"])
        high = max(row["low_inmb"], row["high_inmb"])
        # negative region -> red
        if low < 0:
            ax.barh(y, min(high, 0) - low, left=low, height=0.58, edgecolor="none", color="tab:red")
        # positive region -> blue
        if high > 0:
            ax.barh(y, high - max(low, 0), left=max(low, 0), height=0.58, edgecolor="none", color="tab:blue")

        ax.plot([row["low_inmb"], row["high_inmb"]], [y, y], color="black", linewidth=1.0, alpha=0.5)

    ax.axvline(0, color="black", linewidth=1.1)
    ax.axvline(base_inmb, color="black", linestyle="--", linewidth=1.0)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(df["parameter"])
    ax.invert_yaxis()
    ax.set_xlabel("10-year incremental net monetary benefit (USD), acute THA vs ORIF")
    ax.set_title("Figure 2. One-Way Sensitivity Analysis: 10-Year INMB (WTP=$50,000/QALY)")
    ax.grid(axis="x", alpha=0.25)
    ax.text(0.01, 0.02, "Blue = acute THA preferred; red = ORIF preferred; dashed line = base-case INMB",
            transform=ax.transAxes, fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _preference_region(z: np.ndarray) -> np.ndarray:
    # 1 = acute THA preferred (positive INMB), 0 = ORIF preferred or neutral
    return (z > 0).astype(int)


def make_two_way_utility_figure(out_path: Path):
    orif_vals, tha_vals, z, base = utility_grid()
    pref = _preference_region(z)
    cmap = ListedColormap(["tab:red", "tab:blue"])

    plt.close("all")
    fig, ax = plt.subplots(figsize=(9, 7.5))
    ax.imshow(pref, origin="lower", aspect="auto", cmap=cmap,
              extent=[orif_vals.min(), orif_vals.max(), tha_vals.min(), tha_vals.max()])
    ax.contour(orif_vals, tha_vals, z, levels=[0.0], colors="white", linewidths=1.6)
    ax.plot(base[0], base[1], marker="x", markersize=9, color="black", mew=1.7)
    ax.text(base[0] + 0.01, base[1] + 0.01, "Baseline", fontsize=9, color="black")
    ax.set_xlabel("ORIF well-state utility")
    ax.set_ylabel("THA well-state utility")
    ax.set_title("Figure 3. Two-Way Sensitivity Analysis: Utilities (WTP=$50,000/QALY)")
    ax.text(0.01, 0.02, "Blue = acute THA preferred; red = ORIF preferred",
            transform=ax.transAxes, fontsize=9, bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8, linewidth=0.0))
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def make_two_way_cost_figure(out_path: Path):
    orif_costs, tha_costs, z, base = cost_grid()
    pref = _preference_region(z)
    cmap = ListedColormap(["tab:red", "tab:blue"])

    plt.close("all")
    fig, ax = plt.subplots(figsize=(9, 7.5))
    ax.imshow(pref, origin="lower", aspect="auto", cmap=cmap,
              extent=[orif_costs.min(), orif_costs.max(), tha_costs.min(), tha_costs.max()])
    ax.contour(orif_costs, tha_costs, z, levels=[0.0], colors="white", linewidths=1.6)
    ax.plot(base[0], base[1], marker="x", markersize=9, color="black", mew=1.7)
    ax.text(base[0] + 1500, base[1] + 1500, "Baseline", fontsize=9, color="black")
    ax.set_xlabel("ORIF index cost (USD)")
    ax.set_ylabel("THA index cost (USD)")
    ax.set_title("Figure 4. Two-Way Sensitivity Analysis: Index Costs (WTP=$50,000/QALY)")
    ax.text(0.01, 0.02, "Blue = acute THA preferred; red = ORIF preferred",
            transform=ax.transAxes, fontsize=9, bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8, linewidth=0.0))
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def _node(ax, xy: Tuple[float, float], text: str, color: str, width: float = 1.9, height: float = 0.62, fontsize: int = 9):
    x, y = xy
    patch = FancyBboxPatch((x - width / 2, y - height / 2), width, height,
                           boxstyle="round,pad=0.02,rounding_size=0.08",
                           linewidth=1.0, edgecolor="black", facecolor=color)
    ax.add_patch(patch)
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize)


def _arrow(ax, start: Tuple[float, float], end: Tuple[float, float], *, rad: float = 0.0, lw: float = 1.0, color: str = "0.35", style: str = "-"):
    arrow = FancyArrowPatch(start, end,
                            connectionstyle=f"arc3,rad={rad}",
                            arrowstyle="-|>", mutation_scale=10,
                            linewidth=lw, linestyle=style, color=color,
                            shrinkA=12, shrinkB=12)
    ax.add_patch(arrow)


def make_state_map(out_path: Path):
    # Manual grouped layout tuned to reflect the finalized script.
    pos = {
        "WELL_ORIF": (-4.8, 1.8),
        "DISLOCATION_ORIF": (-4.8, 0.8),
        "ORIF_SSI": (-4.8, -0.2),
        "REFRACTURE": (-4.8, -1.2),
        "ORIF_REOP_TUNNEL": (-2.5, -0.6),
        "POST_ORIF_REOP": (-2.5, -1.6),
        "CONVERSION_THA": (-2.5, 1.8),
        "MEDICAL_COMPLICATION": (-2.5, 0.3),
        "WELL_THA": (0.0, 1.8),
        "DISLOCATION": (0.0, 0.8),
        "PJI_EARLY": (0.0, -0.2),
        "PJI_LATE": (0.0, -1.2),
        "ASEPTIC_LOOSENING": (0.0, -2.2),
        "REV_TUNNEL_ASEPTIC": (2.5, 0.5),
        "REV_TUNNEL_SEPTIC": (2.5, -0.8),
        "POST_REV_ASEPTIC": (5.0, 0.5),
        "POST_REV_SEPTIC": (5.0, -0.8),
        "WELL_REVISED": (7.5, -0.15),
        "DEATH": (10.0, 0.0),
    }

    colors = {
        "orif": "#5ec9c4",
        "tha": "#69a7ff",
        "tunnel": "#b28cff",
        "complication": "#f7b267",
        "shared": "#80cbc4",
        "death": "#555555",
    }

    plt.close("all")
    fig, ax = plt.subplots(figsize=(10.5, 13.2))
    ax.set_xlim(-6.2, 11.3)
    ax.set_ylim(-3.0, 2.8)
    ax.axis("off")

    # Group labels
    ax.text(-4.8, 2.45, "ORIF-native pathway", fontsize=11, ha="center", fontweight="bold")
    ax.text(0.0, 2.45, "Primary / converted THA pathway", fontsize=11, ha="center", fontweight="bold")
    ax.text(4.0, 2.45, "Revision pathway", fontsize=11, ha="center", fontweight="bold")

    for state in ["WELL_ORIF", "DISLOCATION_ORIF", "ORIF_SSI", "REFRACTURE"]:
        _node(ax, pos[state], state.replace("_", "\n"), colors["orif"])
    for state in ["ORIF_REOP_TUNNEL", "POST_ORIF_REOP", "CONVERSION_THA"]:
        _node(ax, pos[state], state.replace("_", "\n"), colors["tunnel"])
    _node(ax, pos["MEDICAL_COMPLICATION"], "MEDICAL\nCOMPLICATION", colors["shared"])

    for state in ["WELL_THA", "DISLOCATION", "PJI_EARLY", "PJI_LATE", "ASEPTIC_LOOSENING"]:
        fill = colors["tha"] if state == "WELL_THA" else colors["complication"]
        _node(ax, pos[state], state.replace("_", "\n"), fill)
    for state in ["REV_TUNNEL_ASEPTIC", "REV_TUNNEL_SEPTIC", "POST_REV_ASEPTIC", "POST_REV_SEPTIC", "WELL_REVISED"]:
        _node(ax, pos[state], state.replace("_", "\n"), colors["tunnel"])
    _node(ax, pos["DEATH"], "DEATH", colors["death"], width=1.4, fontsize=10)

    # ORIF outgoing transitions
    for target, rad in [("CONVERSION_THA", 0.0), ("DISLOCATION_ORIF", 0.0), ("ORIF_SSI", 0.0), ("REFRACTURE", 0.0), ("ORIF_REOP_TUNNEL", -0.18), ("MEDICAL_COMPLICATION", -0.08), ("DEATH", 0.28)]:
        _arrow(ax, pos["WELL_ORIF"], pos[target], rad=rad)
    _arrow(ax, pos["DISLOCATION_ORIF"], pos["WELL_ORIF"], rad=0.0)
    _arrow(ax, pos["DISLOCATION_ORIF"], pos["DEATH"], rad=0.18, style="--")
    _arrow(ax, pos["ORIF_SSI"], pos["ORIF_REOP_TUNNEL"], rad=-0.12)
    _arrow(ax, pos["ORIF_SSI"], pos["WELL_ORIF"], rad=0.18, style="--")
    _arrow(ax, pos["ORIF_SSI"], pos["DEATH"], rad=0.26, style="--")
    _arrow(ax, pos["REFRACTURE"], pos["ORIF_REOP_TUNNEL"], rad=0.0)
    _arrow(ax, pos["REFRACTURE"], pos["DEATH"], rad=0.18, style="--")
    _arrow(ax, pos["ORIF_REOP_TUNNEL"], pos["POST_ORIF_REOP"], rad=0.0)
    _arrow(ax, pos["ORIF_REOP_TUNNEL"], pos["DEATH"], rad=0.18, style="--")
    _arrow(ax, pos["POST_ORIF_REOP"], pos["WELL_ORIF"], rad=-0.18)
    _arrow(ax, pos["POST_ORIF_REOP"], pos["DEATH"], rad=0.22, style="--")

    # Shared medical complication returns
    _arrow(ax, pos["WELL_THA"], pos["MEDICAL_COMPLICATION"], rad=0.12)
    _arrow(ax, pos["MEDICAL_COMPLICATION"], pos["WELL_THA"], rad=-0.08)
    _arrow(ax, pos["MEDICAL_COMPLICATION"], pos["WELL_ORIF"], rad=0.12, style="--")
    _arrow(ax, pos["MEDICAL_COMPLICATION"], pos["DEATH"], rad=0.15, style="--")

    # Conversion and THA pathway
    _arrow(ax, pos["CONVERSION_THA"], pos["WELL_THA"], rad=0.0)
    _arrow(ax, pos["CONVERSION_THA"], pos["DEATH"], rad=0.18, style="--")
    for target, rad in [("DISLOCATION", 0.0), ("PJI_EARLY", 0.0), ("PJI_LATE", 0.0), ("ASEPTIC_LOOSENING", 0.0), ("DEATH", 0.18)]:
        _arrow(ax, pos["WELL_THA"], pos[target], rad=rad)
    _arrow(ax, pos["DISLOCATION"], pos["REV_TUNNEL_ASEPTIC"], rad=0.12)
    _arrow(ax, pos["DISLOCATION"], pos["DISLOCATION"], rad=0.45, style="--")
    _arrow(ax, pos["DISLOCATION"], pos["DEATH"], rad=0.18, style="--")
    _arrow(ax, pos["PJI_EARLY"], pos["WELL_THA"], rad=0.18)
    _arrow(ax, pos["PJI_EARLY"], pos["REV_TUNNEL_SEPTIC"], rad=0.0)
    _arrow(ax, pos["PJI_EARLY"], pos["DEATH"], rad=0.18, style="--")
    _arrow(ax, pos["PJI_LATE"], pos["REV_TUNNEL_SEPTIC"], rad=0.0)
    _arrow(ax, pos["PJI_LATE"], pos["PJI_LATE"], rad=0.45, style="--")
    _arrow(ax, pos["PJI_LATE"], pos["DEATH"], rad=0.14, style="--")
    _arrow(ax, pos["ASEPTIC_LOOSENING"], pos["REV_TUNNEL_ASEPTIC"], rad=0.0)
    _arrow(ax, pos["ASEPTIC_LOOSENING"], pos["DEATH"], rad=0.12, style="--")

    # Revision pathway
    _arrow(ax, pos["REV_TUNNEL_ASEPTIC"], pos["POST_REV_ASEPTIC"], rad=0.0)
    _arrow(ax, pos["REV_TUNNEL_ASEPTIC"], pos["DEATH"], rad=0.12, style="--")
    _arrow(ax, pos["REV_TUNNEL_SEPTIC"], pos["POST_REV_SEPTIC"], rad=0.0)
    _arrow(ax, pos["REV_TUNNEL_SEPTIC"], pos["DEATH"], rad=0.1, style="--")
    _arrow(ax, pos["POST_REV_ASEPTIC"], pos["WELL_REVISED"], rad=0.0)
    _arrow(ax, pos["POST_REV_ASEPTIC"], pos["REV_TUNNEL_ASEPTIC"], rad=0.22, style="--")
    _arrow(ax, pos["POST_REV_ASEPTIC"], pos["DEATH"], rad=0.16, style="--")
    _arrow(ax, pos["POST_REV_SEPTIC"], pos["WELL_REVISED"], rad=0.0)
    _arrow(ax, pos["POST_REV_SEPTIC"], pos["REV_TUNNEL_SEPTIC"], rad=-0.22, style="--")
    _arrow(ax, pos["POST_REV_SEPTIC"], pos["DEATH"], rad=0.12, style="--")
    _arrow(ax, pos["WELL_REVISED"], pos["DISLOCATION"], rad=0.18)
    _arrow(ax, pos["WELL_REVISED"], pos["PJI_LATE"], rad=-0.18)
    _arrow(ax, pos["WELL_REVISED"], pos["DEATH"], rad=0.0)

    ax.text(-5.95, -2.7, "Dashed arrows indicate return / recurrence / mortality pathways omitted from self-loop labeling for readability.", fontsize=8.8)
    ax.set_title("Figure 1. Finalized Markov State Map: Acute THA vs ORIF", fontsize=14, pad=14)
    fig.tight_layout()
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


# ----------------------------- exports -----------------------------

def export_outputs(prefix: str = "") -> Dict[str, Path]:
    outputs = run_base_case_outputs()
    summary_df, events_df, costs_df, qalys_df = summarize_outputs(outputs)
    validation_df = run_final_validation_suite()

    prefix_str = f"{prefix}_" if prefix else ""
    paths = {
        "summary": BASE_DIR / f"{prefix_str}Summary_Outputs.csv",
        "events": BASE_DIR / f"{prefix_str}Event_Outputs.csv",
        "costs": BASE_DIR / f"{prefix_str}Cost_Outputs.csv",
        "qalys": BASE_DIR / f"{prefix_str}QALY_Outputs.csv",
        "validation": BASE_DIR / f"{prefix_str}Validation_Checks.csv",
        "state_map": BASE_DIR / f"{prefix_str}Figure1_State_Map.png",
        "one_way": BASE_DIR / f"{prefix_str}Figure2_OneWay_INMB.png",
        "two_way_util": BASE_DIR / f"{prefix_str}Figure3_TwoWay_Utilities.png",
        "two_way_cost": BASE_DIR / f"{prefix_str}Figure4_TwoWay_Costs.png",
    }

    summary_df.to_csv(paths["summary"], index=False)
    events_df.to_csv(paths["events"], index=False)
    costs_df.to_csv(paths["costs"], index=False)
    qalys_df.to_csv(paths["qalys"], index=False)
    validation_df.to_csv(paths["validation"], index=False)

    make_state_map(paths["state_map"])
    make_one_way_figure(paths["one_way"])
    make_two_way_utility_figure(paths["two_way_util"])
    make_two_way_cost_figure(paths["two_way_cost"])

    return paths


if __name__ == "__main__":
    generated = export_outputs()
    print("Generated files:")
    for name, path in generated.items():
        print(f"- {name}: {path}")

    cfg = ModelConfig()
    cfg.horizon_years = 10.0
    inc = compute_incremental_outputs(cfg)
    print("\n10-year base case:")
    print(f"Acute THA cost: ${inc['cost_tha']:,.0f}")
    print(f"ORIF cost:      ${inc['cost_orif']:,.0f}")
    print(f"Δ cost (THA-ORIF): ${inc['delta_cost']:,.0f}")
    print(f"Acute THA QALYs: {inc['qaly_tha']:.2f}")
    print(f"ORIF QALYs:      {inc['qaly_orif']:.2f}")
    print(f"Δ QALY (THA-ORIF): {inc['delta_qaly']:.2f}")
    print(f"INMB at ${WTP:,.0f}/QALY: ${inc['inmb']:,.0f}")
