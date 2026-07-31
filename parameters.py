# -*- coding: utf-8 -*-
"""
Source parameter definitions for the THA vs ORIF Markov model.

The model uses 3-month cycles and literature-derived base-case values for mortality,
complications, conversion arthroplasty, revision, cost, and utility inputs. Numeric
parameters are annotated with short source labels so that readers can trace assumptions
back to the manuscript tables and cited literature.

Key source mappings:
• 1‑year dislocation after primary THA ≈ 2.8% (Hermansen 2022). DOI: 10.2340/17453674.2022.2754
• Timing of dislocation events: 52% by 3 mo, 71% by 6 mo, 81% by 12 mo (Gillinov 2022). https://pmc.ncbi.nlm.nih.gov/articles/PMC9588560/
• After a first dislocation: 22.3% re‑dislocation at 30 d, 36% at 90 d, 51.2% at 1 y; 10.9% revised within 1 y (Cnudde 2024). https://www.mdpi.com/2077-0383/13/2/598
• PJI incidence after THA: 1.43% ≤90 d, +0.49% between 90 d–1 y (Zeng 2023). DOI: 10.1186/s13018-023-04060-5
• DAIR success acute hip PJI ≈ 67–76%, higher when performed promptly (Salman 2024; Gupta 2023). 
  https://pubmed.ncbi.nlm.nih.gov/39223364/ , https://pmc.ncbi.nlm.nih.gov/articles/PMC11519117/
• 1‑year mortality after THA PJI ≈ 4.22% (Natsuhara 2019). https://pubmed.ncbi.nlm.nih.gov/30642705/
• 30‑day mortality after revision THA ≈ 1.3% overall (Ekeberg 2025, Swedish Perioperative Registry). https://journals.sagepub.com/doi/abs/10.1177/21514593251355915
• ORIF→THA conversion risk: 
  – General cohorts ~13.9% by ≈2.2 y (Christiaans 2024). https://pmc.ncbi.nlm.nih.gov/articles/PMC11666660/
  – Posterior‑wall cohort ~5% at 2 y, 14% at 5–6 y (Firoozabadi 2018). https://upload.orthobullets.com/journalclub/free_pdf/30277977_30277977.pdf
  – Timing of conversions: 52% within 1 y, 79% within 2 y (Cichos 2020, OTA abstract). https://ota.org/sites/files/abstracts/2020/OTA%20AM20%20Paper%20Cichos.pdf
• One‑year primary THA all‑cause revision (registry benchmark) ≈ 0.7–0.8% (NJR headline data via Wartemberg 2019). 
  https://openorthopaedicsjournal.com/VOLUME/13/PAGE/266/FULLTEXT/
• After revision THA, dislocation risk is higher; meta‑estimates around 9% cumulative (Guo 2017; Kahhaleh 2023). 
  https://www.sciencedirect.com/science/article/pii/S1743919116312985 , https://arthroplasty.biomedcentral.com/articles/10.1186/s42836-022-00159-y
• After septic rTHA: 1‑year re‑revision ~30% and 1‑year mortality ~14% (Resl 2024, EPRD). https://pubmed.ncbi.nlm.nih.gov/38821509/
• 1‑year re‑revision after PJI revision THA ≈ 20% (van Veghel 2025). https://www.arthroplastyjournal.org/article/S0883-5403(24)00721-6/fulltext
• US 2019 life tables for background mortality (CDC). https://www.cdc.gov/nchs/data/nvsr/nvsr70/nvsr70-19.pdf

The companion scripts in this repository run the reproducibility checks
and regenerate the manuscript tables and figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional
import math
import numpy as np
import pandas as pd

# ----------------------------- helpers -----------------------------

def annual_to_per_cycle(p_annual: float, cycle_months: int = 3) -> float:
    """Convert an annual probability to per-cycle (cycle_months)."""
    if p_annual < 0 or p_annual > 1:
        raise ValueError("p_annual must be in [0,1]")
    cycles_per_year = 12 / cycle_months
    if p_annual == 0:
        return 0.0
    return 1.0 - (1.0 - p_annual) ** (1.0 / cycles_per_year)

def cumprob_to_per_cycle(p_cum_for_window: float) -> float:
    """For a single cycle that *is* the window (e.g., a specific quarter), the per-cycle = p_cum_for_window."""
    if p_cum_for_window < 0 or p_cum_for_window > 1:
        raise ValueError("p_cum_for_window must be in [0,1]")
    return p_cum_for_window

def pct(x): 
    return f"{100*x:.2f}%"

# ----------------------------- schedules -----------------------------

@dataclass
class WindowSchedule:
    """per-cycle probabilities for 3‑month cycles, keyed by cycle index (0‑based)."""
    by_cycle: Dict[int, float]
    taper_after_24mo: float = 1.0  # multiply hazard after 24 mo (cycles >= 8)

    def get(self, cycle_idx: int) -> float:
        if cycle_idx in self.by_cycle:
            return self.by_cycle[cycle_idx]
        # after 24 months, keep last known hazard * taper
        if len(self.by_cycle) == 0:
            return 0.0
        last_key = max(self.by_cycle.keys())
        return self.by_cycle[last_key] * self.taper_after_24mo

# ----------------------------- base epidemiology (THA) -----------------------------

def build_dislocation_schedule_primary_THA() -> WindowSchedule:
    """
    Primary THA dislocation schedule using Hermansen et al. 2022 and Morison et al. 2016.

    • Hermansen 2022: 2.8% dislocation within 1 year after THA, with quarter-specific risks:
        Q1 1.46%, Q2 0.53%, Q3 0.40%, Q4 0.41% (sums to 2.8% in the first year).
    • Morison 2016: ≈11% dislocation by 10 years after THA for post‑traumatic arthritis.
      Under a constant-hazard approximation this corresponds to ≈1.2%/year, or ≈0.29% per 3‑month cycle.

    We therefore:
      – Use the Hermansen quarter‑specific values in year 1, as per Table 1.
      – Apply a constant 0.29% per‑cycle "late" dislocation hazard from 12 months onward.
    """
    by_cycle = {
        0: 0.0146,  # Q1: 1.46%
        1: 0.0053,  # Q2: 0.53%
        2: 0.0040,  # Q3: 0.40%
        3: 0.0041,  # Q4: 0.41%
        4: 0.0029,  # from 12 months onward: 0.29% per 3‑month cycle
    }
    # keep late hazard roughly constant over the remaining horizon
    return WindowSchedule(by_cycle=by_cycle, taper_after_24mo=1.0)


def build_pji_schedule_primary_THA() -> WindowSchedule:
    """
    PJI schedule from Zeng et al. 2023: 1.43% <=90 d, +0.49% between 90 d and 1 y.
    DOI: 10.1186/s13018-023-04060-5
    """
    by_cycle = {
        0: 0.0143,                     # Q1 (0–3 mo): 1.43%
        1: 0.0049/3.0,                 # spread the remaining 0.49% evenly across Q2–Q4
        2: 0.0049/3.0,
        3: 0.0049/3.0,
    }
    return WindowSchedule(by_cycle=by_cycle, taper_after_24mo=0.50)

def build_allcause_revision_schedule_primary_THA() -> WindowSchedule:
    """
    Revision after THA for post‑traumatic arthritis driven by:
      • Periprosthetic femoral fracture (Lamb et al., 2024): 2.19 per 1000 prosthesis‑years
        ≈0.22%/year ≈0.00055 per 3‑month cycle.
      • Symptomatic aseptic acetabular loosening requiring revision (Ranawat et al., 2009):
        ≈3% by 5 years ⇒ ≈0.6%/year ≈0.0015 per 3‑month cycle (assuming roughly constant hazard).

    In Table 1 these are summarized as:
      – THA_PERIPROSTH_FRAC ≈0.055% per cycle
      – THA_ASEPTIC_LOOSEN ≈0.15% per cycle

    We therefore approximate the combined non‑PJI, non‑dislocation revision hazard as:
        0.00055 + 0.00150 ≈ 0.00205 per 3‑month cycle (≈0.82%/year),
    applied as a roughly constant hazard over the horizon.
    """
    q = 0.00205
    by_cycle = {0: q, 1: q, 2: q, 3: q}
    # Use taper_after_24mo = 1.0 so that the last specified hazard (q) is maintained after 24 months.
    return WindowSchedule(by_cycle=by_cycle, taper_after_24mo=1.0)


# ----------------------------- ORIF-specific epidemiology -----------------------------

def build_orif_ssi_schedule() -> WindowSchedule:
    """
    Surgical site infection (SSI) after acetabular ORIF.
    • Suzuki 2010: 82% of deep infections occurred within 4 weeks after fixation; total ~5.2% base.
      https://pubmed.ncbi.nlm.nih.gov/20127902/
    We map this to ~4.3% in Q1 (≤90 d, which is 82% of 5.2%) and ~0.9% spread across Q2–Q4.
    """
    total_1y = 0.052
    early_share = 0.82
    q1 = total_1y * early_share
    remaining = total_1y * (1.0 - early_share)
    by_cycle = {
        0: q1,                    # 0–3 mo: ~4.3%
        1: remaining/3.0,         # spread remaining across Q2-Q4: ~0.3% each
        2: remaining/3.0,
        3: remaining/3.0,
    }
    return WindowSchedule(by_cycle=by_cycle, taper_after_24mo=0.40)

def build_orif_dislocation_schedule() -> WindowSchedule:
    """
    Redislocation/instability of the native hip after acetabular ORIF is uncommon but reported.
    • Review of native hip dislocation (Dawson‑Amoah 2018): recurrent dislocation is rare (<2% overall).
      https://pmc.ncbi.nlm.nih.gov/articles/PMC6162140/
    We allocate ~1.0% cumulative in year 1 with early front‑loading.
    """
    q1, q2, q3, q4 = 0.006, 0.0025, 0.0010, 0.0005  # sum ≈ 0.010
    by_cycle = {0:q1, 1:q2, 2:q3, 3:q4}
    return WindowSchedule(by_cycle=by_cycle, taper_after_24mo=0.25)

def build_orif_reop_schedule() -> WindowSchedule:
    """
    Aseptic reoperation after acetabular ORIF (hardware failure, nonunion, heterotopic ossification release, etc.).
    • Ljungdahl 2025: ~7% year 1, ~5% year 2 (≈12% cumulative over 2 years).
    We front-load within each year.
    """
    by_cycle = {
        0: 0.035,   # Q1
        1: 0.020,   # Q2
        2: 0.010,   # Q3
        3: 0.005,   # Q4  -> totals ≈7% in year 1
        # Year 2 total ≈5%
        4: 0.020, 
        5: 0.015,
        6: 0.010,
        7: 0.005,
    }
    return WindowSchedule(by_cycle=by_cycle, taper_after_24mo=0.50)

# ----------------------------- ORIF → THA conversion -----------------------------

@dataclass
class ORIFConversionScenario:
    name: str
    target_2y: float
    timing_split: Tuple[float, float]  # share of 2‑y conversions occurring in year1 vs year2

def build_orif_conversion_schedule(s: ORIFConversionScenario) -> WindowSchedule:
    """
    Shapes ORIF→THA conversion to match 2‑year target with timing split:
      – General cohorts: 2.2‑y ≈13.9% (Christiaans 2024) → approximate 2‑y target ~14%.
        https://pmc.ncbi.nlm.nih.gov/articles/PMC11666660/
      – Posterior‑wall cohort: 2‑y ≈5% (Firoozabadi 2018). https://upload.orthobullets.com/journalclub/free_pdf/30277977_30277977.pdf
      – Timing of conversions: ~52% in year 1, ~79% cumulative by year 2 (Cichos 2020). https://ota.org/sites/files/abstracts/2020/OTA%20AM20%20Paper%20Cichos.pdf
    """
    y1_share, y2_share = s.timing_split  # e.g., (0.52, 0.27) so that y1+y2=0.79 of *all* conversions by 2 y
    # We’ll scale so that by 2 years, cumulative equals target_2y and is distributed: year1 = y1_share/y2_total * target_2y, year2 = y2_share/y2_total * target_2y
    y2_total = y1_share + y2_share
    year1 = s.target_2y * (y1_share / y2_total)
    year2 = s.target_2y * (y2_share / y2_total)
    q1=q2=q3=q4=0.0
    q1 = year1 * 0.50   # front‑load within Y1
    q2 = year1 * 0.30
    q3 = year1 * 0.12
    q4 = year1 * 0.08
    q5=q6=q7=q8=0.0
    # Spread Y2 across its four quarters
    q5 = year2 * 0.30
    q6 = year2 * 0.30
    q7 = year2 * 0.25
    q8 = year2 * 0.15
    by_cycle = {0:q1,1:q2,2:q3,3:q4,4:q5,5:q6,6:q7,7:q8}
    return WindowSchedule(by_cycle=by_cycle, taper_after_24mo=0.25)

ORIF_SCENARIOS = {
    # General ORIF cohort: 5% @2y, 14% @5y, 17% @9y; ≈12% @6y in ≥65 (Firoozabadi 2018)
    # Using 5% @2y for base, timing 52% in Y1, 27% in Y2 from Cichos 2020
    "general_orif": ORIFConversionScenario(name="general_orif", target_2y=0.05, timing_split=(0.52, 0.27)),
    # Posterior wall cohort with adverse features can reach ~50% with ≥4mm malreduction
    "posterior_wall": ORIFConversionScenario(name="posterior_wall", target_2y=0.05, timing_split=(0.52, 0.27)),
}

# ----------------------------- dislocation tunnel after first dislocation -----------------------------

@dataclass
class DislocationTunnelParams:
    """
    After a first‑time dislocation:
      • Further dislocation: 22.3% at 30 d, 36.0% at 90 d, 51.2% at 1 y (Cnudde 2024).
      • Revision for dislocation within 1 y: 10.9% (Cnudde 2024).
    https://www.mdpi.com/2077-0383/13/2/598
    We model a maximum 12‑month dwell; if no event, return to WELL state.
    """
    q_recurrence_30d: float = 0.223
    q_recurrence_90d: float = 0.360
    q_recurrence_1y:  float = 0.512
    q_revision_1y:    float = 0.109
    max_dwell_months: int   = 12

# ----------------------------- PJI tunnel -----------------------------

@dataclass
class PJITunnelParams:
    """
    Early vs late PJI and DAIR:
    • Early (≤90 d) vs late: we route cases based on presentation timing.
    • DAIR success (acute PJI): 0.70, consistent with recent DAIR success estimates
      from Salman et al. 2024 and Gupta et al. 2024.
    • 1-year mortality after THA PJI ≈ 4.22% (Natsuhara 2019) applied during the first year from PJI onset.
      https://pubmed.ncbi.nlm.nih.gov/30642705/
    """
    dair_success_early: float = 0.70  # Salman et al., 2024; Gupta et al., 2024
    # For late/chronic PJI, DAIR success is lower; route most to septic revision:
    late_to_septic_revision: float = 0.75
    one_year_mortality_from_PJI: float = 0.0422  # Natsuhara et al., 2019

# ----------------------------- revision tunnels -----------------------------

@dataclass
class RevisionTunnels:
    """
    Peri‑operative tunnels (1 cycle ≈ 3 months) to capture short‑term mortality.
    • 30‑day mortality after revision THA ≈ 1.3% overall (Ekeberg 2025). 
      https://journals.sagepub.com/doi/abs/10.1177/21514593251355915
      We map this to a single cycle by keeping the per‑cycle mortality at 0.013 for septic and 0.010 for aseptic (slightly lower).
    """
    aseptic_30d_mortality: float = 0.010
    septic_30d_mortality: float  = 0.013

@dataclass
class PostRevisionParams:
    """
    Post-revision states (max dwell before returning to WELL_REVISED):
    • Septic rTHA (after PJI): 1-y re-revision ≈20–30% (Resl 2024 EPRD). Use 0.25 base.
      https://pubmed.ncbi.nlm.nih.gov/38821509/
      1-y mortality after septic rTHA ≈ 14% (Resl 2024). https://pubmed.ncbi.nlm.nih.gov/38821509/
    • Aseptic rTHA: use 1-y re-revision ≈8% (Joanroy 2024).
    """
    septic_rerevision_1y: float = 0.25   # Resl et al., 2024
    septic_mortality_1y: float  = 0.14   # Resl et al., 2024
    aseptic_rerevision_1y: float = 0.08  # Joanroy et al., 2024
    max_dwell_months: int = 12

# ----------------------------- background mortality -----------------------------

@dataclass
class AgeMortalityUS2019:
    """
    Background mortality approximated by age bands from US 2019 life tables (CDC NVSR 70‑19).
    https://www.cdc.gov/nchs/data/nvsr/nvsr70/nvsr70-19.pdf
    Values are annual qx for ages within each band.
    """
    start_age: float = 65.0
    cycle_months: int = 3
    band_q: Dict[Tuple[int,int], float] = field(default_factory=lambda: {
        (50,55): 0.005,   # ~0.5%/y (approx from CDC 2019 tables)
        (55,60): 0.007,
        (60,65): 0.010,
        (65,70): 0.018,
        (70,75): 0.028,
        (75,80): 0.045,
        (80,85): 0.070,
        (85,90): 0.110,
        (90,200): 0.170,
    })

    def q_annual_for_age(self, age: float) -> float:
        for (lo,hi),q in self.band_q.items():
            if lo <= age < hi:
                return q
        return list(self.band_q.values())[-1]

    def per_cycle(self, cycle_idx: int) -> float:
        age = self.start_age + (cycle_idx * self.cycle_months)/12.0
        return annual_to_per_cycle(self.q_annual_for_age(age), self.cycle_months)

# ----------------------------- model config -----------------------------

@dataclass
class ModelConfig:
    cycle_months: int = 3
    horizon_years: int = 10

    # Medical complications
    med_comp_tha_1y: float = 0.132      # Kelly et al., 2023 (13.2% medical-only, 90 days)
    med_comp_orif_90d: float = 0.355     # Simske et al., 2023 (35.5% operative subgroup ≥60)
    
    # Refracture parameters
    orif_refracture_1y: float = 0.01     # Lundin et al., 2023 (rare, ≤1% over 1-2 years)
    
    # ORIF mortality parameters from literature review
    orif_30d_mortality: float = 0.08     # Ljungdahl et al., 2025 (approx. 8% >=70y)
    orif_1y_mortality: float = 0.21      # Ljungdahl et al., 2025 (21% >=70y cohort, 95% CI 15-26)
    
    # THA mortality parameters from Albrektsson et al. 2023
    tha_30d_mortality: float = 0.026     # Albrektsson et al., 2023 (2.6% THA/CHP group)
    tha_3mo_mortality: float = 0.087     # Albrektsson et al., 2023 (8.7% at 3 months)
    tha_1y_mortality: float = 0.144      # Albrektsson et al., 2023 (14.4% at 1 year)      
    
    dislocation_primary: WindowSchedule = field(default_factory=build_dislocation_schedule_primary_THA)
    pji_primary: WindowSchedule         = field(default_factory=build_pji_schedule_primary_THA)
    revision_primary: WindowSchedule    = field(default_factory=build_allcause_revision_schedule_primary_THA)

    # ORIF complications (native hip)
    orif_dislocation: WindowSchedule   = field(default_factory=build_orif_dislocation_schedule)
    orif_ssi: WindowSchedule           = field(default_factory=build_orif_ssi_schedule)
    orif_reop: WindowSchedule          = field(default_factory=build_orif_reop_schedule)
    orif_reop_30d_mortality: float     = 0.005  # ~0.5% 30-day mortality for non-arthroplasty reoperation (assumption)

    # ORIF→THA conversion (choose scenario below)
    orif_scenario_key: str = "general_orif"
    orif_conversion: WindowSchedule = field(default_factory=lambda: build_orif_conversion_schedule(ORIF_SCENARIOS["general_orif"]))

    # Tunnels and post-revision
    disloc_tunnel: DislocationTunnelParams = field(default_factory=DislocationTunnelParams)
    pji_tunnel:    PJITunnelParams         = field(default_factory=PJITunnelParams)
    rev_tunnels:   RevisionTunnels         = field(default_factory=RevisionTunnels)
    post_rev:      PostRevisionParams      = field(default_factory=PostRevisionParams)

    # Post-revision "well" epidemiology (risk is higher than primary THA)
    dislocation_revised: float = 0.09   # cumulative (unspecified FU) meta ~9% (Guo 2017)
    pji_after_revision_1y: float = 0.027 # ~2.7% 1-y infection after aseptic rTHA (Bukowski 2022)

    # Periprosthetic femoral fracture rates
    ppfx_primary_1y: float = 0.003      # 0.3% primary THA, Y1
    ppfx_revision_1y: float = 0.01      # 1.0% revision THA, Y1, ≥70y

    # Background mortality
    age_mortality: AgeMortalityUS2019 = field(default_factory=AgeMortalityUS2019)

# ----------------------------- Markov states -----------------------------
STATE_IDX = {
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
    "MEDICAL_COMPLICATION": 17

}
N_STATES = len(STATE_IDX)

# Fraction of THA revision hazard attributable to periprosthetic fracture
THA_PERIPROSTH_FRAC_SHARE = 0.00055 / 0.00205  # from Table 1 and Lamb/Ranawat assumptions

# ----------------------------- Utilities (QOL weights) -----------------------------
# Utilities derived from manuscript appendix values (EQ-5D/SF-6D point estimates).
# Death = 0.0 by definition.
UTIL = {
    "WELL_ORIF": 0.74,            # 0.72–0.75 range (assumed from surgical outcomes literature)
    "WELL_THA": 0.81,             # 0.80–0.82 range (standard post-THA utility)
    "DISLOCATION": 0.78,          # Klit et al., 2021 (EQ-5D-5L 0.78 for dislocation without revision)
    "DISLOCATION_ORIF": 0.78,     # Treat similarly to THA dislocation
    "PJI_EARLY": 0.30,            # Severe infection state
    "PJI_LATE": 0.30,             # Severe infection state
    "REV_TUNNEL_ASEPTIC": 0.35,   # Perioperative revision state
    "REV_TUNNEL_SEPTIC": 0.35,    # Perioperative septic revision
    "POST_REV_ASEPTIC": 0.70,     # Recovery after aseptic revision
    "POST_REV_SEPTIC": 0.70,      # Recovery after septic revision
    "WELL_REVISED": 0.70,         # Stable after revision
    "CONVERSION_THA": 0.30,       # Peri-op tunnel for conversion
    "ORIF_REOP_TUNNEL": 0.35,     # Peri-op tunnel for ORIF reoperation
    "POST_ORIF_REOP": 0.70,       # Recovery after ORIF reoperation
    "DEATH": 0.00,                # Death by definition
    "ASEPTIC_LOOSENING": 0.35,    # Transient detection -> revision tunnel next cycle
    "REFRACTURE": 0.35,           # Transient -> ORIF reop tunnel next cycle
    "MEDICAL_COMPLICATION": 0.50, # 90d medical complications
}

# ----------------------------- Costs (USD) -----------------------------

COST = {
    "INDEX_THA": 40994.0,
    "INDEX_ORIF": 47207.0,
    "REV_ASEPTIC": 30224.0,
    "REV_SEPTIC": 57264.0,
    "DISLOCATION_EP": 25256.0,
    "PJI_EP": 28904.0,
    "CONVERSION_THA": 51243.0,
    "ORIF_REOP": 47207.0,
    "MEDICAL_COMP_EP": 14882.0,  # Major medical complication episode (Schwarzkopf et al., 2019)
}


# ----------------------------- model -----------------------------

class THA_ORIF_Markov:
    
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg
        self.state_names = list(STATE_IDX.keys())
        self.STATE_IDX = STATE_IDX
        self.COST = COST
        self.UTIL = UTIL
        self.n_states = N_STATES
        self.n_cycles = self._cycles()

    def _cycles(self) -> int:
        return int(math.ceil(self.cfg.horizon_years * 12 / self.cfg.cycle_months))

    def _mort(self, cycle_idx: int) -> float:
        return self.cfg.age_mortality.per_cycle(cycle_idx)

    def _add_event_costs(self, counts_delta):
        """Map event deltas in this cycle to costs."""
        cost = 0.0
        if counts_delta.get("dislocations", 0) > 0:
            cost += counts_delta["dislocations"] * COST["DISLOCATION_EP"]
        if counts_delta.get("pji", 0) > 0:
            cost += counts_delta["pji"] * COST["PJI_EP"]
        if counts_delta.get("conversions", 0) > 0:
            cost += counts_delta["conversions"] * COST["CONVERSION_THA"]
        if counts_delta.get("orif_reops", 0) > 0:
            cost += counts_delta["orif_reops"] * COST["ORIF_REOP"]
        if counts_delta.get("medical_comps", 0) > 0:
            cost += counts_delta["medical_comps"] * COST["MEDICAL_COMP_EP"]
        return cost

    def simulate(self, n_cohort=1000, arm="THA"):
        """
        Run the cohort Markov simulation.
        arm: "THA" or "ORIF"
        Returns: df (trace dataframe), counts (dict), tot_cost (float), tot_qaly (float)
        """
        
        # Initialize state vector
        x = np.zeros(self.n_states, dtype=float)
        if arm == "THA":
            x[STATE_IDX["WELL_THA"]] = float(n_cohort)
            # Add index cost
            index_cost = n_cohort * COST["INDEX_THA"]
        elif arm == "ORIF":
            x[STATE_IDX["WELL_ORIF"]] = float(n_cohort)
            index_cost = n_cohort * COST["INDEX_ORIF"]
        else:
            raise ValueError(f"Unknown arm: {arm}")

        # Tracking
        counts = {
            "revisions": 0,
            "dislocations": 0,
            "pji": 0,
            "conversions": 0,
            "orif_reops": 0,
            "refractures": 0,
            "deaths": 0,
            "medical_comps": 0,
        }
        total_cost = index_cost
        total_qaly = 0.0
        
        trace = []
        
        for cycle_idx in range(self.n_cycles):
            # Store current state for tracking
            trace.append(x.copy())
            
            # Accrue utilities for people in each state this cycle
            cycle_qaly = 0.0
            for state_name, idx in STATE_IDX.items():
                if state_name in UTIL:
                    cycle_qaly += x[idx] * UTIL[state_name] * (self.cfg.cycle_months / 12.0)
            total_qaly += cycle_qaly
            
            # Build next state vector
            nxt = np.zeros(self.n_states, dtype=float)
            
            # Background mortality for this cycle
            p_bg_mort = self._mort(cycle_idx)
            
            # Additional treatment-specific mortality
            # ORIF-specific mortality (elderly cohort)
            if cycle_idx == 0:
                p_orif_mort = self.cfg.orif_30d_mortality
            elif cycle_idx < 4:
                # Distribute remaining 1-year mortality across cycles 1-3
                remaining_1y = self.cfg.orif_1y_mortality - self.cfg.orif_30d_mortality
                p_orif_mort = remaining_1y / 3.0
            else:
                p_orif_mort = 0.0
            
            # THA-specific mortality (Albrektsson et al. 2023: acetabular-fracture arthroplasty group)
            if cycle_idx == 0:
                p_tha_mort = self.cfg.tha_30d_mortality
            elif cycle_idx == 1:
                # 3-month mortality minus 30-day
                p_tha_mort = self.cfg.tha_3mo_mortality - self.cfg.tha_30d_mortality
            elif cycle_idx < 4:
                # Distribute remaining 1-year mortality across cycles 2-3
                remaining_1y = self.cfg.tha_1y_mortality - self.cfg.tha_3mo_mortality
                p_tha_mort = remaining_1y / 2.0
            else:
                p_tha_mort = 0.0
            
            # Transition logic for each state
            # WELL_ORIF
            n = x[STATE_IDX["WELL_ORIF"]]
            if n > 0:
                p_conv = self.cfg.orif_conversion.get(cycle_idx)
                p_disloc = self.cfg.orif_dislocation.get(cycle_idx)
                p_ssi = self.cfg.orif_ssi.get(cycle_idx)
                p_reop = self.cfg.orif_reop.get(cycle_idx)
                # Medical complication only in first cycle (90 days)
                p_med = self.cfg.med_comp_orif_90d if cycle_idx == 0 else 0.0
                # Refracture as absolute rate (not fraction)
                p_refrac = self.cfg.orif_refracture_1y / 4.0 if cycle_idx < 4 else 0.0
                
                # Combined mortality (ORIF-specific + background)
                p_mort_combined = p_bg_mort + p_orif_mort
                
                # Competing risks
                p_total = p_conv + p_disloc + p_ssi + p_reop + p_med + p_refrac + p_mort_combined
                if p_total > 1.0:
                    # Normalize if needed
                    scale = 1.0 / p_total
                    p_conv *= scale
                    p_disloc *= scale
                    p_ssi *= scale
                    p_reop *= scale
                    p_med *= scale
                    p_refrac *= scale
                    p_mort_combined *= scale
                    p_stay = 0.0
                else:
                    p_stay = 1.0 - p_total
                
                nxt[STATE_IDX["CONVERSION_THA"]] += n * p_conv
                nxt[STATE_IDX["DISLOCATION_ORIF"]] += n * p_disloc
                nxt[STATE_IDX["PJI_EARLY"]] += n * p_ssi
                nxt[STATE_IDX["REFRACTURE"]] += n * p_refrac
                nxt[STATE_IDX["ORIF_REOP_TUNNEL"]] += n * p_reop
                nxt[STATE_IDX["MEDICAL_COMPLICATION"]] += n * p_med
                nxt[STATE_IDX["WELL_ORIF"]] += n * p_stay
                nxt[STATE_IDX["DEATH"]] += n * p_mort_combined
                
                # Count events
                counts["conversions"] += n * p_conv
                counts["dislocations"] += n * p_disloc
                counts["pji"] += n * p_ssi
                counts["orif_reops"] += n * p_reop
                counts["refractures"] += n * p_refrac
                counts["deaths"] += n * p_mort_combined
                counts["medical_comps"] += n * p_med
                
                # Add episodic costs
                total_cost += n * p_conv * COST["CONVERSION_THA"]
                total_cost += n * p_disloc * COST["DISLOCATION_EP"]
                total_cost += n * p_ssi * COST["PJI_EP"]
                total_cost += n * p_reop * COST["ORIF_REOP"]
                total_cost += n * p_med * COST["MEDICAL_COMP_EP"]
            
            # WELL_THA (with THA-specific mortality)
            n = x[STATE_IDX["WELL_THA"]]
            if n > 0:
                p_disloc = self.cfg.dislocation_primary.get(cycle_idx)
                p_pji = self.cfg.pji_primary.get(cycle_idx)
                p_rev = self.cfg.revision_primary.get(cycle_idx)
                # Partition the revision hazard into periprosthetic fracture vs other aseptic causes
                p_refrac_tha = p_rev * THA_PERIPROSTH_FRAC_SHARE

                # Kelly et al. 13.2% is a 1-year risk, so convert to a
                # per-cycle hazard over 4 three-month cycles:
                if cycle_idx < 4:
                    p_med = 1.0 - (1.0 - self.cfg.med_comp_tha_1y) ** (1.0 / 4.0)
                else:
                    p_med = 0.0
                
                # Combined mortality (THA-specific + background)
                p_mort_combined = p_bg_mort + p_tha_mort
                
                p_total = p_disloc + p_pji + p_rev + p_med + p_mort_combined
                if p_total > 1.0:
                    scale = 1.0 / p_total
                    p_disloc *= scale
                    p_pji *= scale
                    p_rev *= scale
                    p_med *= scale
                    p_mort_combined *= scale
                    p_stay = 0.0
                else:
                    p_stay = 1.0 - p_total
                
                nxt[STATE_IDX["DISLOCATION"]] += n * p_disloc
                # Split PJI into early vs late based on cycle
                if cycle_idx == 0:
                    nxt[STATE_IDX["PJI_EARLY"]] += n * p_pji
                else:
                    nxt[STATE_IDX["PJI_LATE"]] += n * p_pji
                nxt[STATE_IDX["ASEPTIC_LOOSENING"]] += n * p_rev
                nxt[STATE_IDX["MEDICAL_COMPLICATION"]] += n * p_med
                nxt[STATE_IDX["WELL_THA"]] += n * p_stay
                nxt[STATE_IDX["DEATH"]] += n * p_mort_combined
                
                counts["dislocations"] += n * p_disloc
                counts["pji"] += n * p_pji
                counts["refractures"] += n * p_refrac_tha
                counts["deaths"] += n * p_mort_combined
                counts["medical_comps"] += n * p_med
                
                total_cost += n * p_disloc * COST["DISLOCATION_EP"]
                total_cost += n * p_pji * COST["PJI_EP"]
                total_cost += n * p_med * COST["MEDICAL_COMP_EP"]
            
            # DISLOCATION (THA dislocation tunnel - max 12 months)
            n = x[STATE_IDX["DISLOCATION"]]
            if n > 0:
                # Simplified: revision at rate from literature, recurrence, or resolve
                p_rev = self.cfg.disloc_tunnel.q_revision_1y / 4.0  # spread over year
                p_recur = self.cfg.disloc_tunnel.q_recurrence_90d / 4.0
                
                p_total = p_rev + p_recur + p_bg_mort
                if p_total > 1.0:
                    scale = 1.0 / p_total
                    p_rev *= scale
                    p_recur *= scale
                    p_bg_mort *= scale
                    p_stay = 0.0
                else:
                    p_stay = 1.0 - p_total
                
                nxt[STATE_IDX["REV_TUNNEL_ASEPTIC"]] += n * p_rev
                nxt[STATE_IDX["DISLOCATION"]] += n * (p_stay + p_recur)  # stay in tunnel
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                
                counts["revisions"] += n * p_rev
                counts["dislocations"] += n * p_recur
                counts["deaths"] += n * p_bg_mort
                
                total_cost += n * p_rev * COST["REV_ASEPTIC"]
                total_cost += n * p_recur * COST["DISLOCATION_EP"]
            
            # PJI_EARLY (attempt DAIR or proceed to septic revision)
            n = x[STATE_IDX["PJI_EARLY"]]
            if n > 0:
                p_dair_success = self.cfg.pji_tunnel.dair_success_early
                p_septic_rev = 1.0 - p_dair_success  # rest go to septic revision
                p_mort_pji = self.cfg.pji_tunnel.one_year_mortality_from_PJI / 4.0
                
                p_total = p_septic_rev + p_mort_pji
                if p_total > 1.0:
                    scale = 1.0 / p_total
                    p_septic_rev *= scale
                    p_mort_pji *= scale
                
                nxt[STATE_IDX["WELL_THA"]] += n * p_dair_success  # DAIR success returns to well
                nxt[STATE_IDX["REV_TUNNEL_SEPTIC"]] += n * p_septic_rev
                nxt[STATE_IDX["DEATH"]] += n * p_mort_pji
                
                counts["revisions"] += n * p_septic_rev
                counts["deaths"] += n * p_mort_pji
                
                total_cost += n * p_septic_rev * COST["REV_SEPTIC"]
            
            # PJI_LATE (chronic - mostly goes to septic revision)
            n = x[STATE_IDX["PJI_LATE"]]
            if n > 0:
                p_septic_rev = self.cfg.pji_tunnel.late_to_septic_revision
                p_mort_pji = self.cfg.pji_tunnel.one_year_mortality_from_PJI / 4.0
                
                p_total = p_septic_rev + p_mort_pji
                if p_total > 1.0:
                    scale = 1.0 / p_total
                    p_septic_rev *= scale
                    p_mort_pji *= scale
                    p_stay = 0.0
                else:
                    p_stay = 1.0 - p_total
                
                nxt[STATE_IDX["REV_TUNNEL_SEPTIC"]] += n * p_septic_rev
                nxt[STATE_IDX["PJI_LATE"]] += n * p_stay
                nxt[STATE_IDX["DEATH"]] += n * p_mort_pji
                
                counts["revisions"] += n * p_septic_rev
                counts["deaths"] += n * p_mort_pji
                
                total_cost += n * p_septic_rev * COST["REV_SEPTIC"]
            
            # CONVERSION_THA (tunnel state - one cycle, then to WELL_THA)
            n = x[STATE_IDX["CONVERSION_THA"]]
            if n > 0:
                p_mort = self.cfg.rev_tunnels.aseptic_30d_mortality
                nxt[STATE_IDX["WELL_THA"]] += n * (1.0 - p_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort
            
            # REV_TUNNEL_ASEPTIC (one cycle, then to POST_REV_ASEPTIC)
            n = x[STATE_IDX["REV_TUNNEL_ASEPTIC"]]
            if n > 0:
                p_mort = self.cfg.rev_tunnels.aseptic_30d_mortality
                nxt[STATE_IDX["POST_REV_ASEPTIC"]] += n * (1.0 - p_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort
            
            # REV_TUNNEL_SEPTIC (one cycle, then to POST_REV_SEPTIC)
            n = x[STATE_IDX["REV_TUNNEL_SEPTIC"]]
            if n > 0:
                p_mort = self.cfg.rev_tunnels.septic_30d_mortality
                nxt[STATE_IDX["POST_REV_SEPTIC"]] += n * (1.0 - p_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort
            
            # POST_REV_ASEPTIC (dwell up to 12 months, then to WELL_REVISED)
            n = x[STATE_IDX["POST_REV_ASEPTIC"]]
            if n > 0:
                p_rerev = self.cfg.post_rev.aseptic_rerevision_1y / 4.0
                p_to_well = 0.25  # exit to WELL_REVISED over 4 quarters
                
                p_total = p_rerev + p_to_well + p_bg_mort
                if p_total > 1.0:
                    scale = 1.0 / p_total
                    p_rerev *= scale
                    p_to_well *= scale
                    p_bg_mort *= scale
                    p_stay = 0.0
                else:
                    p_stay = 1.0 - p_total
                
                nxt[STATE_IDX["REV_TUNNEL_ASEPTIC"]] += n * p_rerev
                nxt[STATE_IDX["WELL_REVISED"]] += n * p_to_well
                nxt[STATE_IDX["POST_REV_ASEPTIC"]] += n * p_stay
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                
                counts["revisions"] += n * p_rerev
                counts["deaths"] += n * p_bg_mort
                
                total_cost += n * p_rerev * COST["REV_ASEPTIC"]
            
            # POST_REV_SEPTIC (dwell up to 12 months, then to WELL_REVISED)
            n = x[STATE_IDX["POST_REV_SEPTIC"]]
            if n > 0:
                p_rerev = self.cfg.post_rev.septic_rerevision_1y / 4.0
                p_mort_septic = self.cfg.post_rev.septic_mortality_1y / 4.0
                p_to_well = 0.25
                
                p_total = p_rerev + p_mort_septic + p_to_well
                if p_total > 1.0:
                    scale = 1.0 / p_total
                    p_rerev *= scale
                    p_mort_septic *= scale
                    p_to_well *= scale
                    p_stay = 0.0
                else:
                    p_stay = 1.0 - p_total
                
                nxt[STATE_IDX["REV_TUNNEL_SEPTIC"]] += n * p_rerev
                nxt[STATE_IDX["WELL_REVISED"]] += n * p_to_well
                nxt[STATE_IDX["POST_REV_SEPTIC"]] += n * p_stay
                nxt[STATE_IDX["DEATH"]] += n * (p_bg_mort + p_mort_septic)
                
                counts["revisions"] += n * p_rerev
                counts["deaths"] += n * (p_bg_mort + p_mort_septic)
                
                total_cost += n * p_rerev * COST["REV_SEPTIC"]
            
            # WELL_REVISED (higher risk than primary)
            n = x[STATE_IDX["WELL_REVISED"]]
            if n > 0:
                p_disloc = annual_to_per_cycle(self.cfg.dislocation_revised)
                p_pji = annual_to_per_cycle(self.cfg.pji_after_revision_1y)
                
                p_total = p_disloc + p_pji + p_bg_mort
                if p_total > 1.0:
                    scale = 1.0 / p_total
                    p_disloc *= scale
                    p_pji *= scale
                    p_bg_mort *= scale
                    p_stay = 0.0
                else:
                    p_stay = 1.0 - p_total
                
                nxt[STATE_IDX["DISLOCATION"]] += n * p_disloc
                nxt[STATE_IDX["PJI_LATE"]] += n * p_pji
                nxt[STATE_IDX["WELL_REVISED"]] += n * p_stay
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                
                counts["dislocations"] += n * p_disloc
                counts["pji"] += n * p_pji
                counts["deaths"] += n * p_bg_mort
                
                total_cost += n * p_disloc * COST["DISLOCATION_EP"]
                total_cost += n * p_pji * COST["PJI_EP"]
            
            # DISLOCATION_ORIF (resolves to WELL_ORIF after one cycle)
            n = x[STATE_IDX["DISLOCATION_ORIF"]]
            if n > 0:
                nxt[STATE_IDX["WELL_ORIF"]] += n * (1.0 - p_bg_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                counts["deaths"] += n * p_bg_mort
            
            # ORIF_REOP_TUNNEL (one cycle, then to POST_ORIF_REOP)
            n = x[STATE_IDX["ORIF_REOP_TUNNEL"]]
            if n > 0:
                p_mort = self.cfg.orif_reop_30d_mortality
                nxt[STATE_IDX["POST_ORIF_REOP"]] += n * (1.0 - p_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_mort
                counts["deaths"] += n * p_mort
            
            # POST_ORIF_REOP (returns to WELL_ORIF after one cycle)
            n = x[STATE_IDX["POST_ORIF_REOP"]]
            if n > 0:
                nxt[STATE_IDX["WELL_ORIF"]] += n * (1.0 - p_bg_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                counts["deaths"] += n * p_bg_mort
            
            # ASEPTIC_LOOSENING (routes to revision tunnel immediately)
            n = x[STATE_IDX["ASEPTIC_LOOSENING"]]
            if n > 0:
                nxt[STATE_IDX["REV_TUNNEL_ASEPTIC"]] += n * (1.0 - p_bg_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                counts["revisions"] += n * (1.0 - p_bg_mort)
                counts["deaths"] += n * p_bg_mort
                total_cost += n * (1.0 - p_bg_mort) * COST["REV_ASEPTIC"]
            
            # REFRACTURE (routes to ORIF reop tunnel)
            n = x[STATE_IDX["REFRACTURE"]]
            if n > 0:
                nxt[STATE_IDX["ORIF_REOP_TUNNEL"]] += n * (1.0 - p_bg_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                counts["deaths"] += n * p_bg_mort
            
            # MEDICAL_COMPLICATION (resolves after one cycle)
            n = x[STATE_IDX["MEDICAL_COMPLICATION"]]
            if n > 0:
                # Return to the well state corresponding to the treatment arm.
                if arm == "THA":
                    nxt[STATE_IDX["WELL_THA"]] += n * (1.0 - p_bg_mort)
                else:
                    nxt[STATE_IDX["WELL_ORIF"]] += n * (1.0 - p_bg_mort)
                nxt[STATE_IDX["DEATH"]] += n * p_bg_mort
                counts["deaths"] += n * p_bg_mort
            
            # DEATH is absorbing
            nxt[STATE_IDX["DEATH"]] += x[STATE_IDX["DEATH"]]
            
            # Update state vector
            x = nxt
        
        # Add final state to trace
        trace.append(x.copy())
        
        # Build summary dataframe with state, count, pct columns
        final_state = x
        summary_data = []
        total_alive = n_cohort - final_state[STATE_IDX["DEATH"]]
        
        for state_name in self.state_names:
            idx = STATE_IDX[state_name]
            count = final_state[idx]
            pct = (count / n_cohort) * 100.0
            summary_data.append({
                "state": state_name,
                "count": count,
                "pct": pct
            })
        
        df = pd.DataFrame(summary_data)
        
        return df, counts, total_cost, total_qaly


# ----------------------------- run a quick demo -----------------------------
if __name__ == "__main__":
    cfg = ModelConfig()

    # Print results at 90 days, 1 year, 2 years, 5 years, and 10 years.
    horizons = [(0.25, "90 days"), (1, "1 year"), (2, "2 years"), (5, "5 years"), (10, "10 years")]
    for years, label in horizons:
        cfg.horizon_years = years
        model = THA_ORIF_Markov(cfg)  # Recreate model with new horizon
        
        for arm in ["THA", "ORIF"]:
            df, counts, tot_cost, tot_qaly = model.simulate(n_cohort=1000, arm=arm)
            print(f"\n=== Cohort end‑states at {label} — {arm} arm ===")
            print(df[["state","count","pct"]].sort_values("count", ascending=False).to_string(index=False, formatters={"count": lambda x: f"{x:.0f}", "pct": lambda x: f"{x:.2f}"}))
            print(f"\nTotals: Cost=${tot_cost:,.0f}, QALYs={tot_qaly:.2f}")
            print("\nCumulative events:")
            for k,v in counts.items():
                print(f"  {k:>15}: {v:,.1f}")
