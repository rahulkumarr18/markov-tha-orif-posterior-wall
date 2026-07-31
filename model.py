
# -*- coding: utf-8 -*-
"""
Primary THA vs ORIF Markov model implementation.

This module defines the health-state structure and transition logic used for the
base-case and sensitivity analyses reported in the manuscript. The model uses a
1,000-patient cohort by default, 3-month cycles, competing-risk transition
normalization, a dedicated ORIF surgical-site-infection pathway, and explicit
accounting for ORIF reoperation events following refracture.

Converted THA patients enter the shared WELL_THA state after the conversion
tunnel. Time since conversion is not modeled with a separate long-term tunnel.
"""

from __future__ import annotations

import math
from typing import Dict
import numpy as np
import pandas as pd

import parameters as original

ModelConfig = original.ModelConfig
annual_to_per_cycle = original.annual_to_per_cycle
COST = dict(original.COST)
UTIL = dict(original.UTIL)
UTIL["ORIF_SSI"] = 0.30

THA_PERIPROSTH_FRAC_SHARE = original.THA_PERIPROSTH_FRAC_SHARE

STATE_IDX: Dict[str, int] = {
    "WELL_ORIF": 0,
    "WELL_THA": 1,
    "DISLOCATION": 2,
    "PJI_EARLY": 3,
    "PJI_LATE": 4,
    "CONVERSION_THA": 5,
    "REV_TUNNEL_ASEPTIC": 6,
    "REV_TUNNEL_SEPTIC": 7,
    "POST_REV_ASEPTIC": 8,
    "POST_REV_SEPTIC": 9,
    "WELL_REVISED": 10,
    "DEATH": 11,
    "DISLOCATION_ORIF": 12,
    "ORIF_REOP_TUNNEL": 13,
    "POST_ORIF_REOP": 14,
    "ASEPTIC_LOOSENING": 15,
    "REFRACTURE": 16,
    "MEDICAL_COMPLICATION": 17,
    "ORIF_SSI": 18,
}
N_STATES = len(STATE_IDX)


class THA_ORIF_Markov:
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg
        self.STATE_IDX = STATE_IDX
        self.state_names = [k for k, _ in sorted(STATE_IDX.items(), key=lambda kv: kv[1])]
        self.n_states = N_STATES
        self.n_cycles = int(math.ceil(self.cfg.horizon_years * 12 / self.cfg.cycle_months))

    def _mort(self, cycle_idx: int) -> float:
        return self.cfg.age_mortality.per_cycle(cycle_idx)

    @staticmethod
    def _combine_mortality(*probs: float) -> float:
        survival = 1.0
        for p in probs:
            p = max(0.0, min(1.0, float(p)))
            survival *= (1.0 - p)
        return 1.0 - survival

    @staticmethod
    def _normalize(prob_dict):
        total = float(sum(prob_dict.values()))
        if total > 1.0 and total > 0.0:
            scale = 1.0 / total
            prob_dict = {k: v * scale for k, v in prob_dict.items()}
            stay = 0.0
        else:
            stay = 1.0 - total
        return prob_dict, stay

    def simulate(self, n_cohort=1000, arm="THA", return_trace=False):
        s = self.STATE_IDX
        x = np.zeros(self.n_states, dtype=float)

        if arm == "THA":
            x[s["WELL_THA"]] = float(n_cohort)
            total_cost = n_cohort * COST["INDEX_THA"]
        elif arm == "ORIF":
            x[s["WELL_ORIF"]] = float(n_cohort)
            total_cost = n_cohort * COST["INDEX_ORIF"]
        else:
            raise ValueError(f"Unknown arm: {arm}")

        counts = {
            "revisions": 0.0,
            "dislocations": 0.0,
            "pji": 0.0,
            "infection_events": 0.0,
            "conversions": 0.0,
            "orif_reops": 0.0,
            "refractures": 0.0,
            "deaths": 0.0,
            "medical_comps": 0.0,
        }
        total_qaly = 0.0
        trace = [x.copy()]

        for cycle_idx in range(self.n_cycles):
            cycle_qaly = 0.0
            for state_name, idx in s.items():
                cycle_qaly += x[idx] * UTIL.get(state_name, 0.0) * (self.cfg.cycle_months / 12.0)
            total_qaly += cycle_qaly

            nxt = np.zeros(self.n_states, dtype=float)
            p_bg_mort = self._mort(cycle_idx)

            if cycle_idx == 0:
                # Cycle 0 spans 0-3 months. ORIF has no published 3-month figure, so the
                # 30-day rate is used as the best-available proxy for the full cycle. THA
                # has a published 3-month (90-day) rate (Albrektsson et al. 2023) and that
                # figure is applied directly so the model's 90-day checkpoint matches the
                # literature target instead of only reflecting the finer 30-day rate.
                p_orif_specific = self.cfg.orif_30d_mortality
                p_tha_specific = self.cfg.tha_3mo_mortality
            elif cycle_idx < 4:
                rem_orif = self.cfg.orif_1y_mortality - self.cfg.orif_30d_mortality
                p_orif_specific = rem_orif / 3.0
                rem_tha = self.cfg.tha_1y_mortality - self.cfg.tha_3mo_mortality
                p_tha_specific = rem_tha / 3.0
            else:
                p_orif_specific = 0.0
                p_tha_specific = 0.0

            # WELL_ORIF
            n = x[s["WELL_ORIF"]]
            if n > 0:
                probs = {
                    "conv": self.cfg.orif_conversion.get(cycle_idx),
                    "disloc": self.cfg.orif_dislocation.get(cycle_idx),
                    "ssi": self.cfg.orif_ssi.get(cycle_idx),
                    "reop": self.cfg.orif_reop.get(cycle_idx),
                    "med": self.cfg.med_comp_orif_90d if (arm == "ORIF" and cycle_idx == 0) else 0.0,
                    "refrac": self.cfg.orif_refracture_1y / 4.0 if cycle_idx < 4 else 0.0,
                    "death": self._combine_mortality(p_bg_mort, p_orif_specific if arm == "ORIF" else 0.0),
                }
                probs, p_stay = self._normalize(probs)

                nxt[s["CONVERSION_THA"]] += n * probs["conv"]
                nxt[s["DISLOCATION_ORIF"]] += n * probs["disloc"]
                nxt[s["ORIF_SSI"]] += n * probs["ssi"]
                nxt[s["ORIF_REOP_TUNNEL"]] += n * probs["reop"]
                nxt[s["MEDICAL_COMPLICATION"]] += n * probs["med"]
                nxt[s["REFRACTURE"]] += n * probs["refrac"]
                nxt[s["DEATH"]] += n * probs["death"]
                nxt[s["WELL_ORIF"]] += n * p_stay

                counts["conversions"] += n * probs["conv"]
                counts["dislocations"] += n * probs["disloc"]
                counts["pji"] += n * probs["ssi"]
                counts["infection_events"] += n * probs["ssi"]
                counts["orif_reops"] += n * probs["reop"]
                counts["refractures"] += n * probs["refrac"]
                counts["deaths"] += n * probs["death"]
                counts["medical_comps"] += n * probs["med"]

                total_cost += n * probs["conv"] * COST["CONVERSION_THA"]
                total_cost += n * probs["disloc"] * COST["DISLOCATION_EP"]
                total_cost += n * probs["ssi"] * COST["PJI_EP"]
                total_cost += n * probs["reop"] * COST["ORIF_REOP"]
                total_cost += n * probs["med"] * COST["MEDICAL_COMP_EP"]

            # WELL_THA
            n = x[s["WELL_THA"]]
            if n > 0:
                p_med = (1.0 - (1.0 - self.cfg.med_comp_tha_1y) ** (1.0 / 4.0)) if (arm == "THA" and cycle_idx < 4) else 0.0
                probs = {
                    "disloc": self.cfg.dislocation_primary.get(cycle_idx),
                    "pji": self.cfg.pji_primary.get(cycle_idx),
                    "rev": self.cfg.revision_primary.get(cycle_idx),
                    "med": p_med,
                    "death": self._combine_mortality(p_bg_mort, p_tha_specific if arm == "THA" else 0.0),
                }
                probs, p_stay = self._normalize(probs)

                nxt[s["DISLOCATION"]] += n * probs["disloc"]
                if cycle_idx == 0:
                    nxt[s["PJI_EARLY"]] += n * probs["pji"]
                else:
                    nxt[s["PJI_LATE"]] += n * probs["pji"]
                nxt[s["ASEPTIC_LOOSENING"]] += n * probs["rev"]
                nxt[s["MEDICAL_COMPLICATION"]] += n * probs["med"]
                nxt[s["DEATH"]] += n * probs["death"]
                nxt[s["WELL_THA"]] += n * p_stay

                counts["dislocations"] += n * probs["disloc"]
                counts["pji"] += n * probs["pji"]
                counts["infection_events"] += n * probs["pji"]
                counts["refractures"] += n * probs["rev"] * THA_PERIPROSTH_FRAC_SHARE
                counts["deaths"] += n * probs["death"]
                counts["medical_comps"] += n * probs["med"]

                total_cost += n * probs["disloc"] * COST["DISLOCATION_EP"]
                total_cost += n * probs["pji"] * COST["PJI_EP"]
                total_cost += n * probs["med"] * COST["MEDICAL_COMP_EP"]

            # DISLOCATION
            n = x[s["DISLOCATION"]]
            if n > 0:
                probs = {
                    "rev": self.cfg.disloc_tunnel.q_revision_1y / 4.0,
                    "recur": self.cfg.disloc_tunnel.q_recurrence_90d / 4.0,
                    "death": p_bg_mort,
                }
                probs, p_stay = self._normalize(probs)

                nxt[s["REV_TUNNEL_ASEPTIC"]] += n * probs["rev"]
                nxt[s["DISLOCATION"]] += n * (probs["recur"] + p_stay)
                nxt[s["DEATH"]] += n * probs["death"]

                counts["revisions"] += n * probs["rev"]
                counts["dislocations"] += n * probs["recur"]
                counts["deaths"] += n * probs["death"]

                total_cost += n * probs["rev"] * COST["REV_ASEPTIC"]
                total_cost += n * probs["recur"] * COST["DISLOCATION_EP"]

            # PJI_EARLY
            n = x[s["PJI_EARLY"]]
            if n > 0:
                p_death = self.cfg.pji_tunnel.one_year_mortality_from_PJI / 4.0
                p_survive = 1.0 - p_death
                p_well = p_survive * self.cfg.pji_tunnel.dair_success_early
                p_rev = p_survive * (1.0 - self.cfg.pji_tunnel.dair_success_early)

                nxt[s["WELL_THA"]] += n * p_well
                nxt[s["REV_TUNNEL_SEPTIC"]] += n * p_rev
                nxt[s["DEATH"]] += n * p_death

                counts["revisions"] += n * p_rev
                counts["deaths"] += n * p_death
                total_cost += n * p_rev * COST["REV_SEPTIC"]

            # PJI_LATE
            n = x[s["PJI_LATE"]]
            if n > 0:
                p_death = self.cfg.pji_tunnel.one_year_mortality_from_PJI / 4.0
                p_survive = 1.0 - p_death
                p_rev = p_survive * self.cfg.pji_tunnel.late_to_septic_revision
                p_stay = p_survive - p_rev

                nxt[s["REV_TUNNEL_SEPTIC"]] += n * p_rev
                nxt[s["PJI_LATE"]] += n * p_stay
                nxt[s["DEATH"]] += n * p_death

                counts["revisions"] += n * p_rev
                counts["deaths"] += n * p_death
                total_cost += n * p_rev * COST["REV_SEPTIC"]

            # ORIF_SSI
            n = x[s["ORIF_SSI"]]
            if n > 0:
                p_death = p_bg_mort
                nxt[s["ORIF_REOP_TUNNEL"]] += n * (1.0 - p_death)
                nxt[s["DEATH"]] += n * p_death

                counts["orif_reops"] += n * (1.0 - p_death)
                counts["deaths"] += n * p_death
                total_cost += n * (1.0 - p_death) * COST["ORIF_REOP"]

            # CONVERSION_THA
            n = x[s["CONVERSION_THA"]]
            if n > 0:
                p_mort = self.cfg.rev_tunnels.aseptic_30d_mortality
                nxt[s["WELL_THA"]] += n * (1.0 - p_mort)
                nxt[s["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort

            # REV_TUNNEL_ASEPTIC
            n = x[s["REV_TUNNEL_ASEPTIC"]]
            if n > 0:
                p_mort = self.cfg.rev_tunnels.aseptic_30d_mortality
                nxt[s["POST_REV_ASEPTIC"]] += n * (1.0 - p_mort)
                nxt[s["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort

            # REV_TUNNEL_SEPTIC
            n = x[s["REV_TUNNEL_SEPTIC"]]
            if n > 0:
                p_mort = self.cfg.rev_tunnels.septic_30d_mortality
                nxt[s["POST_REV_SEPTIC"]] += n * (1.0 - p_mort)
                nxt[s["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort

            # POST_REV_ASEPTIC
            n = x[s["POST_REV_ASEPTIC"]]
            if n > 0:
                probs = {
                    "rerev": self.cfg.post_rev.aseptic_rerevision_1y / 4.0,
                    "to_well": 0.25,
                    "death": p_bg_mort,
                }
                probs, p_stay = self._normalize(probs)

                nxt[s["REV_TUNNEL_ASEPTIC"]] += n * probs["rerev"]
                nxt[s["WELL_REVISED"]] += n * probs["to_well"]
                nxt[s["POST_REV_ASEPTIC"]] += n * p_stay
                nxt[s["DEATH"]] += n * probs["death"]

                counts["revisions"] += n * probs["rerev"]
                counts["deaths"] += n * probs["death"]
                total_cost += n * probs["rerev"] * COST["REV_ASEPTIC"]

            # POST_REV_SEPTIC
            n = x[s["POST_REV_SEPTIC"]]
            if n > 0:
                probs = {
                    "rerev": self.cfg.post_rev.septic_rerevision_1y / 4.0,
                    "to_well": 0.25,
                    "death": self._combine_mortality(p_bg_mort, self.cfg.post_rev.septic_mortality_1y / 4.0),
                }
                probs, p_stay = self._normalize(probs)

                nxt[s["REV_TUNNEL_SEPTIC"]] += n * probs["rerev"]
                nxt[s["WELL_REVISED"]] += n * probs["to_well"]
                nxt[s["POST_REV_SEPTIC"]] += n * p_stay
                nxt[s["DEATH"]] += n * probs["death"]

                counts["revisions"] += n * probs["rerev"]
                counts["deaths"] += n * probs["death"]
                total_cost += n * probs["rerev"] * COST["REV_SEPTIC"]

            # WELL_REVISED
            n = x[s["WELL_REVISED"]]
            if n > 0:
                probs = {
                    "disloc": annual_to_per_cycle(self.cfg.dislocation_revised),
                    "pji": annual_to_per_cycle(self.cfg.pji_after_revision_1y),
                    "death": p_bg_mort,
                }
                probs, p_stay = self._normalize(probs)

                nxt[s["DISLOCATION"]] += n * probs["disloc"]
                nxt[s["PJI_LATE"]] += n * probs["pji"]
                nxt[s["WELL_REVISED"]] += n * p_stay
                nxt[s["DEATH"]] += n * probs["death"]

                counts["dislocations"] += n * probs["disloc"]
                counts["pji"] += n * probs["pji"]
                counts["infection_events"] += n * probs["pji"]
                counts["deaths"] += n * probs["death"]

                total_cost += n * probs["disloc"] * COST["DISLOCATION_EP"]
                total_cost += n * probs["pji"] * COST["PJI_EP"]

            # DISLOCATION_ORIF
            n = x[s["DISLOCATION_ORIF"]]
            if n > 0:
                nxt[s["WELL_ORIF"]] += n * (1.0 - p_bg_mort)
                nxt[s["DEATH"]] += n * p_bg_mort
                counts["deaths"] += n * p_bg_mort

            # ORIF_REOP_TUNNEL
            n = x[s["ORIF_REOP_TUNNEL"]]
            if n > 0:
                p_mort = self.cfg.orif_reop_30d_mortality
                nxt[s["POST_ORIF_REOP"]] += n * (1.0 - p_mort)
                nxt[s["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort

            # POST_ORIF_REOP
            n = x[s["POST_ORIF_REOP"]]
            if n > 0:
                nxt[s["WELL_ORIF"]] += n * (1.0 - p_bg_mort)
                nxt[s["DEATH"]] += n * p_bg_mort
                counts["deaths"] += n * p_bg_mort

            # ASEPTIC_LOOSENING
            n = x[s["ASEPTIC_LOOSENING"]]
            if n > 0:
                nxt[s["REV_TUNNEL_ASEPTIC"]] += n * (1.0 - p_bg_mort)
                nxt[s["DEATH"]] += n * p_bg_mort
                counts["revisions"] += n * (1.0 - p_bg_mort)
                counts["deaths"] += n * p_bg_mort
                total_cost += n * (1.0 - p_bg_mort) * COST["REV_ASEPTIC"]

            # REFRACTURE
            n = x[s["REFRACTURE"]]
            if n > 0:
                p_reop = 1.0 - p_bg_mort
                nxt[s["ORIF_REOP_TUNNEL"]] += n * p_reop
                nxt[s["DEATH"]] += n * p_bg_mort
                counts["orif_reops"] += n * p_reop
                counts["deaths"] += n * p_bg_mort
                total_cost += n * p_reop * COST["ORIF_REOP"]

            # MEDICAL_COMPLICATION
            n = x[s["MEDICAL_COMPLICATION"]]
            if n > 0:
                if arm == "THA":
                    nxt[s["WELL_THA"]] += n * (1.0 - p_bg_mort)
                else:
                    nxt[s["WELL_ORIF"]] += n * (1.0 - p_bg_mort)
                nxt[s["DEATH"]] += n * p_bg_mort
                counts["deaths"] += n * p_bg_mort

            # DEATH absorbing
            nxt[s["DEATH"]] += x[s["DEATH"]]

            x = nxt
            trace.append(x.copy())

        rows = []
        for state_name in self.state_names:
            count = x[s[state_name]]
            rows.append({"state": state_name, "count": count, "pct": (count / n_cohort) * 100.0})
        df = pd.DataFrame(rows)

        if return_trace:
            return df, counts, total_cost, total_qaly, np.array(trace)
        return df, counts, total_cost, total_qaly




def run_reviewer_validation_suite(n_cohort=1000):
    """Run internal validity and face-validity checks."""
    results = []

    # 1) Base-case conservation / monotonicity checks for each arm
    cfg = ModelConfig()
    model = THA_ORIF_Markov(cfg)
    for arm in ["THA", "ORIF"]:
        df, counts, total_cost, total_qaly, trace = model.simulate(n_cohort=n_cohort, arm=arm, return_trace=True)
        cycle_totals = trace.sum(axis=1)
        death_series = trace[:, STATE_IDX["DEATH"]]
        results.append({
            "test_group": "base_case",
            "test_name": f"{arm}_cohort_conservation",
            "passed": bool(np.all(np.abs(cycle_totals - n_cohort) < 1e-9)),
            "value": float(np.max(np.abs(cycle_totals - n_cohort))),
            "expected": 0.0,
            "details": "Maximum absolute deviation from starting cohort across cycles",
        })
        results.append({
            "test_group": "base_case",
            "test_name": f"{arm}_death_absorbing",
            "passed": bool(np.all(np.diff(death_series) >= -1e-9)),
            "value": float(np.min(np.diff(death_series))) if len(death_series) > 1 else 0.0,
            "expected": "non-decreasing",
            "details": "Death state occupancy should never decline",
        })
        results.append({
            "test_group": "base_case",
            "test_name": f"{arm}_no_negative_states",
            "passed": bool(np.min(trace) >= -1e-9),
            "value": float(np.min(trace)),
            "expected": ">= 0",
            "details": "All state occupancies should remain non-negative",
        })

    # 2) Zero-event edge case
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
    # zero background mortality
    cfg0.age_mortality.per_cycle = lambda cycle_idx: 0.0
    model0 = THA_ORIF_Markov(cfg0)
    for arm, state in [("THA","WELL_THA"),("ORIF","WELL_ORIF")]:
        df, counts, cost, qaly, trace = model0.simulate(n_cohort=n_cohort, arm=arm, return_trace=True)
        final_main = float(df.loc[df["state"]==state,"count"].iloc[0])
        final_death = float(df.loc[df["state"]=="DEATH","count"].iloc[0])
        results.append({
            "test_group": "edge_case",
            "test_name": f"{arm}_zero_event_stability",
            "passed": bool(abs(final_main - n_cohort) < 1e-9 and abs(final_death) < 1e-9),
            "value": final_main,
            "expected": n_cohort,
            "details": "With all hazards removed, the cohort should remain entirely in the initial well state",
        })

    # 3) Short-horizon schedule benchmarks
    cfg1 = ModelConfig()
    cfg1.horizon_years = 0.25
    cfg1.age_mortality.per_cycle = lambda cycle_idx: 0.0
    cfg1.orif_30d_mortality = 0.0
    cfg1.orif_1y_mortality = 0.0
    cfg1.tha_30d_mortality = 0.0
    cfg1.tha_3mo_mortality = 0.0
    cfg1.tha_1y_mortality = 0.0
    model1 = THA_ORIF_Markov(cfg1)
    _, c_tha, *_ = model1.simulate(n_cohort=n_cohort, arm="THA", return_trace=False)
    _, c_orif, *_ = model1.simulate(n_cohort=n_cohort, arm="ORIF", return_trace=False)
    benchmarks = [
        ("THA_Q1_dislocation_events", c_tha["dislocations"], 1000*cfg1.dislocation_primary.get(0), "Q1 THA dislocation events should match the specified quarter-1 schedule when mortality is zero"),
        ("THA_Q1_pji_events", c_tha["pji"], 1000*cfg1.pji_primary.get(0), "Q1 THA infection events should match the specified quarter-1 schedule when mortality is zero"),
        ("ORIF_Q1_ssi_events", c_orif["pji"], 1000*cfg1.orif_ssi.get(0), "Q1 ORIF SSI events should match the specified quarter-1 schedule when mortality is zero"),
        ("ORIF_Q1_medical_comp_events", c_orif["medical_comps"], 1000*cfg1.med_comp_orif_90d, "Q1 ORIF medical complications should match the specified 90-day risk when mortality is zero"),
    ]
    for name, observed, expected, details in benchmarks:
        results.append({
            "test_group": "benchmark",
            "test_name": name,
            "passed": bool(abs(observed - expected) < 1e-6),
            "value": float(observed),
            "expected": float(expected),
            "details": details,
        })

    # 4) Refracture-triggered ORIF reoperation accounting
    cfg_r = ModelConfig()
    cfg_r.horizon_years = 1.25
    cfg_r.orif_refracture_1y = 0.10
    cfg_r.age_mortality.per_cycle = lambda cycle_idx: 0.0
    cfg_r.orif_30d_mortality = 0.0
    cfg_r.orif_1y_mortality = 0.0
    cfg_r.orif_reop_30d_mortality = 0.0
    for attr in ["orif_conversion", "orif_dislocation", "orif_ssi", "orif_reop"]:
        sched = getattr(cfg_r, attr)
        if hasattr(sched, "by_cycle"):
            sched.by_cycle = {k: 0.0 for k in sched.by_cycle}
            sched.taper_after_24mo = 0.0
    cfg_r.med_comp_orif_90d = 0.0
    model_r = THA_ORIF_Markov(cfg_r)
    _, counts_r, cost_r, _, _ = model_r.simulate(n_cohort=n_cohort, arm="ORIF", return_trace=True)
    results.append({
        "test_group": "benchmark",
        "test_name": "ORIF_refracture_to_reop_accounting",
        "passed": bool(abs(counts_r["orif_reops"] - counts_r["refractures"]) < 1e-6),
        "value": float(counts_r["orif_reops"]),
        "expected": float(counts_r["refractures"]),
        "details": "Under isolated refracture-only conditions, each refracture should generate one ORIF reoperation event",
    })

    return pd.DataFrame(results)

def run_standard_outputs():
    cfg = ModelConfig()
    horizons = [(0.25, "90 days"), (1, "1 year"), (2, "2 years"), (5, "5 years"), (10, "10 years")]
    outputs = []
    for years, label in horizons:
        cfg.horizon_years = years
        model = THA_ORIF_Markov(cfg)
        for arm in ["THA", "ORIF"]:
            df, counts, total_cost, total_qaly, trace = model.simulate(n_cohort=1000, arm=arm, return_trace=True)
            outputs.append((label, arm, df, counts, total_cost, total_qaly, trace))
    return outputs


if __name__ == "__main__":
    for label, arm, df, counts, total_cost, total_qaly, trace in run_standard_outputs():
        print(f"\n=== Patched model end-states at {label} — {arm} arm ===")
        print(df.sort_values("count", ascending=False).to_string(index=False, formatters={"count": lambda x: f"{x:.2f}", "pct": lambda x: f"{x:.2f}"}))
        print(f"Total cost = ${total_cost:,.0f}")
        print(f"Total QALYs = {total_qaly:.2f}")
        print(f"Final-state total = {df['count'].sum():.6f}")
