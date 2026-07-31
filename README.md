# THA vs ORIF Markov Model

This repository provides the code and generated outputs for the decision-analytic Markov model comparing acute total hip arthroplasty (THA) with open reduction and internal fixation (ORIF) for geriatric posterior wall acetabular fractures.

The repository is intended for manuscript reviewers and readers who want to inspect the model assumptions, rerun the base-case analysis, and reproduce the reported tables and figures.

## Contents

| File | Purpose |
| --- | --- |
| `parameters.py` | Source parameter definitions and literature-derived default inputs. |
| `model.py` | Primary Markov model implementation used for reported analyses. |
| `reproduce_results.py` | Reproducibility driver that regenerates the final outputs and figures. |
| `Summary_Outputs.csv` | Base-case summary by treatment arm and time horizon. |
| `Event_Outputs.csv` | Event and end-state outputs corresponding to the manuscript event table. |
| `Cost_Outputs.csv` | Cost outputs corresponding to the manuscript cost table. |
| `QALY_Outputs.csv` | QALY outputs corresponding to the manuscript QALY table. |
| `Validation_Checks.csv` | Internal validation checks used to assess model behavior. |
| `Figure1_State_Map.png` | Markov state map. |
| `Figure2_OneWay_INMB.png` | One-way deterministic sensitivity analysis. |
| `Figure3_TwoWay_Utilities.png` | Two-way utility sensitivity analysis. |
| `Figure4_TwoWay_Costs.png` | Two-way index-cost sensitivity analysis. |
| `requirements.txt` | Minimal Python dependencies required to rerun the model. |

Manuscript drafts, local virtual environments, temporary Word files, and older exploratory scripts are intentionally excluded.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python reproduce_results.py
```

Running `reproduce_results.py` regenerates all `*_Outputs.csv` tables and `Figure*.png` figures in the repository directory.

## Expected Base-Case Output

For a 1,000-patient cohort at 10 years, the base-case model reports:

| Outcome | Acute THA | ORIF |
| --- | ---: | ---: |
| Total cost | `$57,272,115` | `$69,444,749` |
| Per-patient cost | `$57,272` | `$69,445` |
| Total QALYs | `6,331.41` | `5,607.50` |
| Per-patient QALYs | `6.33` | `5.61` |

The 10-year incremental QALY gain for acute THA versus ORIF is `723.91` QALYs per 1,000 patients.

## Validation Checks

The final model includes internal checks for:

- cohort conservation across cycles;
- absorbing behavior of the death state;
- nonnegative state occupancy;
- zero-event stability;
- short-horizon schedule benchmarks;
- ORIF surgical-site-infection pathway isolation;
- converted-THA schedule separation;
- refracture-to-ORIF-reoperation accounting.

Validation results are written to `Validation_Checks.csv`.

## Notes for Reviewers

The model uses quarterly cycles over prespecified time horizons of 90 days, 1 year, 2 years, 5 years, and 10 years. Costs are reported from a U.S. health-system perspective. Utilities and transition probabilities are deterministic base-case values derived from literature review and proxy assumptions where direct estimates were unavailable.

The public code package is designed to reproduce the manuscript tables and figures, not to serve as a general-purpose clinical decision-support tool.
