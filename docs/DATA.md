# Data

Everything in the repository is synthetic or public. Real plant data is confidential, which is
the reason PlantSentinel exists, so the demo runs on generated data that is built to look and
misbehave like a real CMMS export, with one true story planted in it.

## Sources

| Path | What | How it's made |
|---|---|---|
| `data/raw/ai4i2020.csv` | 10,000 machine readings with failure labels | [AI4I 2020 Predictive Maintenance](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset), UCI, CC BY 4.0 |
| `data/synthetic/assets.csv` | 30 assets: pumps P-101…P-115, compressors C-201…C-206, heat exchangers E-301…E-305, motors M-401…M-404 | `scripts/generate_synthetic.py` |
| `data/synthetic/work_orders.csv` | 491 work orders, Nov 2023 – Nov 2026 | same script, `--seed 42` |
| `data/synthetic/work_orders_truth.csv` | the true failure mode of every work order (evaluation only) | same script |
| `data/synthetic/clusters_fallback.json` | saved clustering used by the seed (15 modes) | `scripts/run_clustering.py` |
| `data/synthetic/asset_conditions.csv` | one held-out AI4I row per asset, its "current operating condition" | `scripts/train_risk_model.py` |
| `data/scans/INSP-00{1..4}_*.jpg` | four scanned-looking inspection reports | `scripts/make_demo_scans.py` |
| `data/docs/manuals/` | pump O&M manual, seal reliability SOP (Markdown, page-marked) | written for the demo |
| `data/docs/demo_injection/` | vendor bulletin hiding a prompt-injection instruction | written for the demo; never indexed for normal search |

All generators are deterministic: the same seed gives byte-identical output.

## Work orders: realistic noise

Columns: `id, tag, date, description, action_taken, downtime_hrs, cost_inr`.

The descriptions are written the way technicians type them:

- abbreviations: `lkg`, `brg`, `vib`, `temp`, `mech`, `o/l`, `DE`, `NDE`
- typos (adjacent letters swapped), mixed case, trailing `!!`
- Hinglish: `seal leak hua`, `bearing sound aa raha hai`, `SEAL LEAK HUA PHIR SE`
- the tag written inside the text, with or without the hyphen
- occasional duplicate entries of one event in different words

Result: 491 work orders written **316 different ways**; the seal-leakage failure mode alone
appears in 35 wordings. Background failures are capped at one per asset and failure mode
inside the last 180 days, so no asset becomes a bad actor by accident (tested across seeds).

## The planted story

| Asset | What happens | Where it shows |
|---|---|---|
| **P-101** (pump, criticality A) | 9 mechanical-seal failures since May 2024, about every 150 days, then 4 in the last 180 days, about every 50 days. Each time the seal is simply replaced. | work orders WO-0069 … WO-0486; cost ₹4.1 lakh and 37 h downtime in the last six months |
| | The RCA inspection after WO-0486 finds **shaft misalignment 0.3 mm at the coupling**, soft foot 0.15 mm, vibration 7.1 mm/s at 2× running speed | `INSP-004_P-101.jpg` |
| | The pump manual allows **0.05 mm** parallel offset and links misalignment to seal face damage | `centrifugal_pump_om_manual.md`, page 3 |
| | Its operating condition is an AI4I overstrain failure row | risk 1.00, top reason overstrain 3.1× typical |
| C-203 (compressor, A) | bearing overheating, 3 events in 180 days; the inspection finds degraded oil and a fouled cooler | INSP-003 |
| E-302 (heat exchanger, B) | tube fouling, 3 events in 180 days | INSP-002 |
| P-104 | a healthy pump with a clean inspection, a distractor | INSP-001 |

The correct answer to "Why does P-101 keep failing?" is therefore misalignment: correct the
soft foot, laser-align the pump and motor, then fit a new seal. Replacing the seal alone
treats the symptom.

## AI4I features used by the risk model

Raw: air temperature, process temperature, rotational speed, torque, tool wear, product type
(L/M/H, shown as duty class). Engineered: heat-dissipation margin (process − air temperature),
mechanical power (torque × speed), overstrain (torque × wear). The five failure-type flags
(TWF, HDF, PWF, OSF, RNF) are never features: they give away the label.

## Reproducing the numbers

| Number | Command | Where it's written |
|---|---|---|
| Clustering ARI 0.93, homogeneity 0.96, silhouette 0.63 | `uv run python scripts/run_clustering.py` (needs Ollama) | `models/metrics.json` → `clustering` |
| Risk F1 0.84, ROC-AUC 0.975, PR-AUC 0.875 | `uv run python scripts/train_risk_model.py` | `models/metrics.json` → `risk_model` |
| Bad actors P-101, C-203, E-302; P-101 MTBF 150 → 51 days | `.\make.ps1 seed` (verify step) or `GET /api/bad-actors` | — |
| Model benchmark | `uv run python scripts/benchmark_models.py <models…>` | stdout |
| Demo beats | `.\make.ps1 offline-check` | stdout |

The ARI above uses the saved clustering, named with the full 7B model. Re-clustering live with
the 6 GB default model (`--cluster live`) gives 0.90.
