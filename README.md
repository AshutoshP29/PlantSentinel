# PlantSentinel

**Your plant's failure history, read by an AI that never leaves the building.**

PlantSentinel reads years of messy maintenance records, scanned inspection reports and equipment
manuals. It finds the equipment that keeps failing, explains the root cause from the plant's own
documents, and drafts the work order. Everything runs on one laptop: the models, the data and
the app. It shows on screen that nothing leaves the machine.

> **Status:** the full demo runs end to end on the demo laptop (RTX 4050, 6 GB) **with Wi-Fi
> off**: `.\make.ps1 offline-check` reports `ISOLATED` and `DEMO READY`.

**More documentation:** [Architecture](docs/ARCHITECTURE.md) (components, flows, privacy
layers, design decisions, known gaps) · [Data](docs/DATA.md) (datasets, the planted story,
reproducing the numbers) · [Project brief](docs/PROJECT_BRIEF.md). AI coding assistants: see
[CLAUDE.md](CLAUDE.md) and the skills in `.claude/skills/`.

## What it does

| | Feature | How |
|---|---|---|
| F1 | **Ingest** CMMS exports, scanned inspection reports, PDF/Markdown manuals | CSV/XLSX loader with CMMS header variants; vision model transcribes scans; manuals chunked into ChromaDB |
| F2 | **Failure-mode clustering** of free text like `mech seal lkg`, `SEAL LEAK HUA PHIR SE` | abbreviation expansion, `nomic-embed-text`, HDBSCAN with centroid merge, LLM-named clusters |
| F3 | **Bad-actor ranking** | per asset × failure mode: events in 180 days, MTBF now vs before, cost trend, criticality-weighted score |
| F4 | **Risk prediction** with reasons | XGBoost on AI4I 2020 plus SHAP top-3 reasons ("overstrain 3× typical") |
| F5 | **Root-cause agent** with citations | LangGraph tool-calling agent; every claim cites `[INSP-004]`, a manual page or `[WO-0486]` |
| F6 | **Documents** | work order `.docx`, bad-actor report `.xlsx` |
| F7 | **Privacy guard** | tool allow-list, role permissions (technician / engineer), audit log, blocked-exfiltration drill, live outbound-connection count, internal-only Docker network |

## Architecture

```
 browser ──► gateway (nginx, 127.0.0.1:8080)          network "edge"   (only published port)
                │  /api                                ─────────────────────────────────────
                ▼                                      network "plant"  (internal: true)
             backend (FastAPI)  ──►  ollama (GPU)       no route to the internet or the host
             SQLite · analytics ──►  chroma (vectors)
             agent · guard · docgen
```

Privacy is enforced in three layers, so one failing layer is not enough to leak data:

1. **Network:** `backend`, `ollama` and `chroma` sit on an internal-only Docker network. They
   can't reach the internet, a raw IP or the host, even with Wi-Fi on
   (`scripts/check_isolation.py`).
2. **Guard:** the agent can only call seven allow-listed tools. Any other call, or one carrying
   a URL or e-mail, is blocked, recorded in `audit_log` / `blocked_attempts` and shown as a red
   alert.
3. **Proof on screen:** the Privacy tab shows live outbound connections (0) from the kernel's
   socket table, plus the audit log and the injection drill.

## Quick start (Windows, fresh clone)

**Prerequisites:** [uv](https://docs.astral.sh/uv/), Docker Desktop (WSL2 backend), an NVIDIA
GPU, [Ollama](https://ollama.com). Node.js is only needed for frontend development.

```powershell
# 1. Models (once, needs internet). Defaults are sized for a 6 GB GPU.
ollama pull qwen2.5:7b-instruct-q3_K_M   # agent, cluster naming, inspection extraction
ollama pull qwen2.5vl:3b                 # reads scanned inspection reports
ollama pull nomic-embed-text             # embeddings
ollama pull qwen2.5:3b-instruct          # optional faster fallback

# 2. Python tooling + git hooks (every teammate)
.\make.ps1 setup

# 3. Copy the model weights into the Docker volume (offline, ~3 min for 13 GB)
docker compose --profile setup run --rm model-copy

# 4. Quit the Ollama app in the system tray (it would hold the GPU), then start the stack
docker compose up -d --build             # first build needs internet; later runs work offline

# 5. Load the demo data inside the stack (~2 min: data, clusters, risk model, manuals, 4 scans)
docker compose exec backend python /app/scripts/seed_demo.py --reset

# 6. Check the whole demo (run with Wi-Fi off to prove it works offline)
.\make.ps1 offline-check                 # -> ISOLATED ... DEMO READY
```

Open **http://127.0.0.1:8080**. On Linux/macOS use `make <target>` instead of `.\make.ps1`.

## Demo script (about 3 minutes)

**Before presenting:**
- Quit the Ollama tray app.
- Run `.\make.ps1 demo-check` once to load the model into GPU memory (the first answer after a
  start takes ~50 s; warm answers take ~20 s).
- Switch Wi-Fi off.

| Time | Beat | What the audience sees |
|---|---|---|
| 20 s | **Problem** | Failure history sits in messy CMMS text and scans; manuals go unread; the data is too confidential for cloud AI. |
| 30 s | **Ingest** | Upload work orders: `mech seal lkg`, `SEAL LEAK HUA PHIR SE P-101` become clean failure modes. |
| 30 s | **Dashboard** | *P-101 is the top bad actor: 4 mechanical-seal failures in 6 months, MTBF down 66% (150 → 51 days).* |
| 60 s | **Ask PlantSentinel:** *"Why does P-101 keep failing and what should we do?"* | Steps stream live (history → inspection → manuals → risk). Answer: *shaft misalignment 0.3 mm at the coupling [INSP-004] against the pump manual's 0.05 mm limit (p. 3)*, then correct the soft foot, laser-align, replace the seal. Draft the work order and download the `.docx`. |
| 30 s | **Privacy** | External connections: 0. Run the injection test: the poisoned vendor bulletin tells the AI to send data to `evil.example`; the guard blocks it, names the document and page, and logs it. |
| 10 s | **Close** | One avoided unplanned failure pays for a per-plant annual licence. |

`uv run python scripts/agent_cli.py rehearse -n 3` (or inside the backend container) asks the
P-101 question three times and checks each beat: history, INSP-004 cited, the 0.05 mm
manual passage, and a `.docx`.

## Results

Measured on the demo laptop with the default models.

| | Metric | Value |
|---|---|---|
| **Clustering** (491 work orders) | agreement with true failure modes (ARI) | **0.93** |
| | homogeneity / silhouette (cosine) | 0.96 / 0.63 |
| | failure modes found | 15 (14 true) |
| **Risk model** (AI4I 2020 held-out test set, 3.4% failures) | F1 | **0.84** |
| | precision / recall | 0.87 / 0.81 |
| | ROC-AUC / PR-AUC | **0.975** / 0.875 |
| **Planted story** | P-101 seal failures, last 180 days | 4 (MTBF 150 → 51 days, −66%) |
| | bad actors flagged | exactly 3: P-101, C-203, E-302 |
| **Agent** | demo question, warm | ~20–40 s, cites INSP-004 and the manual; rehearsal 3/3 |
| **Inspections** | 4 scans read by the vision model | ~105 s, at seeding time |

The decision threshold was tuned on a validation split; test metrics come from data the model
never saw. All metrics are written to `models/metrics.json`.

### Models and VRAM

The default models fit entirely in 6 GB of GPU memory. Benchmark on the RTX 4050
(`scripts/benchmark_models.py`):

| LLM | On GPU | Speed | Tool choice | Cluster ARI |
|---|---|---|---|---|
| `qwen2.5:7b-instruct` (q4) | 82% | 24 tok/s | good | 0.93 |
| **`qwen2.5:7b-instruct-q3_K_M`** (default) | **100%** | **39–41 tok/s** | good | 0.90 |
| `qwen2.5:3b-instruct` | 100% | 76 tok/s | weaker | 0.87 |

On an 8 GB+ GPU set `LLM_MODEL=qwen2.5:7b-instruct` and `VISION_MODEL=qwen2.5vl:7b` in `.env`.
The vision model only transcribes scans; the text model extracts the findings (the small vision
model returns empty JSON when asked to structure text).

## Data

All data is synthetic or public; no real plant data is in the repository.

| Path | Contents |
|---|---|
| `data/raw/ai4i2020.csv` | [AI4I 2020 Predictive Maintenance](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset) (UCI, CC BY 4.0), 10,000 rows |
| `data/synthetic/` | 30 assets, 491 noisy work orders over 3 years (abbreviations, typos, Hinglish, duplicates), ground-truth labels, saved clusters, asset operating conditions. Regenerate with `scripts/generate_synthetic.py --seed 42` |
| `data/scans/` | 4 scanned inspection reports (`scripts/make_demo_scans.py`). **INSP-004 (P-101):** *shaft misalignment 0.3 mm observed at coupling* |
| `data/docs/manuals/` | pump O&M manual (alignment tolerance 0.05 mm) and seal reliability SOP |
| `data/docs/demo_injection/` | poisoned vendor bulletin for the exfiltration drill (not indexed for normal search) |

**The planted story:** P-101 (criticality A) has four seal failures in six months, each time
the seal was simply replaced. The RCA inspection finds 0.3 mm shaft misalignment, the manual
says 0.05 mm is the limit, so the root cause is misalignment: laser-align, then replace the
seal. C-203 (bearing overheating) and E-302 (tube fouling) are secondary bad actors.

## Configuration

Settings live in `backend/app/config.py`; every one can be overridden by an environment variable
or a `.env` file.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` (Compose: `http://ollama:11434`) | model server |
| `LLM_MODEL` / `VISION_MODEL` / `EMBED_MODEL` | see above | models |
| `NAMING_MODEL` | `LLM_MODEL` | optional separate model for cluster naming |
| `ANALYSIS_AS_OF` | latest work-order date | end of the 180-day analysis window |
| `AGENT_MAX_TOOL_CALLS` | `8` | tool calls per question |
| `DB_PATH`, `DATA_DIR`, `MODELS_DIR`, `CHROMA_DIR`, `CHROMA_HOST` | repo paths / embedded Chroma | storage |
| `VITE_LIVE` / `VITE_USE_MOCK` | screens with a backend are live | gateway build: which screens use real data |

## Local development (without Docker)

```powershell
.\make.ps1 seed                                   # fresh database from the committed data
uv run uvicorn app.main:app --app-dir backend --reload    # API on :8000 (uses host Ollama)
cd frontend; npm ci; npm run dev:live             # UI on :5173, /api proxied to :8000
```

| Command | Purpose |
|---|---|
| `.\make.ps1 lint` / `test` / `format` | ruff, pytest (no Ollama or GPU needed), auto-fix |
| `.\make.ps1 seed [--cluster live]` | load the demo data (`--cluster live` re-clusters with Ollama) |
| `.\make.ps1 demo-check` | every demo beat through the gateway |
| `.\make.ps1 offline-check` | isolation check, then the demo check (run with Wi-Fi off) |
| `uv run python scripts/run_clustering.py` | re-cluster, evaluate against ground truth, save the fallback |
| `uv run python scripts/train_risk_model.py` | retrain XGBoost, write metrics and asset conditions |
| `uv run python scripts/agent_cli.py ask "..."` | ask the agent from the terminal |
| `uv run pytest -m integration` | tests against real models |

## API

All routes are under `/api`; the spec's paths (`/analytics/...`, `/assets/{tag}/risk`) are
aliases of the same handlers.

| Area | Routes |
|---|---|
| Health | `GET /health`, `GET /agent/status` |
| Dashboard | `GET /dashboard/summary`, `GET /bad-actors`, `GET /failure-modes`, `GET /mtbf-trend` (`window_days=90/180/365`) |
| Assets | `GET /assets`, `GET /assets/{tag}`, `GET /assets/{tag}/work-orders`, `GET /risk/{tag}`, `GET /assets/{tag}/inspection` |
| Ingest | `POST /ingest/work-orders` (CSV/XLSX), `POST /cluster` |
| Agent | `POST /agent/ask` `{question, tag}` (SSE: `step`, `token`, `done`, `blocked`, `error`), `POST /agent/chat` |
| Documents | `POST /documents/work-order`, `POST /documents/bad-actor-report`, `GET /documents`, `GET /documents/{id}/download` |
| Privacy | `GET /privacy/status`, `GET /privacy/blocked`, `GET /audit-log`, `POST /privacy/injection-test` (SSE) |

Agent tools: `get_asset_history`, `get_bad_actors`, `predict_risk`, `search_manuals`,
`read_inspection`, `generate_work_order`, `export_report`.

### Roles

The UI sends the user's role in the `X-Role` header; a missing or unknown role is treated as a
technician (least privilege). The backend enforces it (`app/guard/roles.py`):

| Role | View, ask the agent | Generate work orders | Export reports |
|---|---|---|---|
| `technician` | yes | no | no |
| `engineer` | yes | yes | yes |

For a technician the agent is only offered the five read-only tools. If the model still tries
`generate_work_order` or `export_report`, the guard blocks the call, writes it to the audit log
and shows it as a blocked attempt. The document endpoints return `403`. Every audit row records
the user and role.

## Repository layout

```
backend/app/
  analytics/   clustering, bad actors, risk model, dashboard figures
  agent/       LangGraph agent, tools, RAG, inspections, prompts, injection drill
  guard/       audit guard (allow-list + audit_log + blocked_attempts), role permissions
  privacy/     connection monitor, injection drill
  ingestion/   CSV/XLSX work orders, scan seeding entry point
  docgen/      work order .docx, bad-actor report .xlsx
  api/         FastAPI routers
frontend/      React + Vite + TypeScript + Tailwind + Recharts
scripts/       seed_demo, demo_check, generate_synthetic, train_risk_model, run_clustering,
               make_demo_scans, agent_cli, benchmark_models, check_isolation, check_no_ai_coauthor
deploy/gateway nginx config        data/   datasets, scans, manuals        models/   metrics
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Answers crawl (<1 token/s) | The host Ollama app holds the GPU. Quit it from the tray, then `docker compose restart ollama`. Check with `docker compose exec ollama ollama ps` (should say `100% GPU`). |
| First answer takes ~50 s | Normal cold start; run `.\make.ps1 demo-check` before presenting. |
| `docker compose build` fails on a download | Network dropped mid-build; re-run (the uv cache keeps what was downloaded). |
| Seed step 7 (inspections) warns | `qwen2.5vl:3b` or the LLM isn't in the Ollama volume; pull it on the host, re-run `model-copy`. |
| Risk endpoint returns 503 | The model isn't trained: re-run the seed (it trains if missing). |
| Docker "cannot find the file specified" | Docker Desktop isn't running; start it. |
| Drafting a work order returns 403 | The signed-in role is a technician; sign in with a role that can export reports. |
