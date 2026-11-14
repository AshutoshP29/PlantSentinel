# PlantSentinel

Your plant's failure history, read by an AI that never leaves the building. It finds recurring
failures, explains the root cause from your own manuals, and drafts the work order.

Everything runs locally: models are served by Ollama on the host, and the app makes no
external network calls at runtime.

> Status: step 1 of the build (repo skeleton, tooling, CI). Setup, seeding, running and the
> demo script will be added as the build progresses.

## Prerequisites (Windows)

- [uv](https://docs.astral.sh/uv/) (manages Python 3.12; don't use system Python)
- Node.js LTS (frontend)
- Docker Desktop
- Ollama, with the models pulled:

  ```powershell
  # defaults in backend/app/config.py (sized for a 6 GB GPU)
  ollama pull qwen2.5:7b-instruct-q3_K_M   # chat / agent (LLM_MODEL)
  ollama pull qwen2.5vl:3b                 # scanned inspections (VISION_MODEL)
  ollama pull nomic-embed-text             # embeddings (EMBED_MODEL)
  ollama pull qwen2.5:3b-instruct          # faster fallback (set LLM_MODEL=qwen2.5:3b-instruct)
  # 8+ GB GPU: qwen2.5:7b-instruct and qwen2.5vl:7b
  ```

## Setup

```powershell
uv sync --group dev                 # add --extra ocr for PaddleOCR (large download)
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

Or run `.\make.ps1 setup`. On Linux/macOS use `make setup`.

**Every teammate must run the `pre-commit install` line.** It enables ruff on commit and the
commit-message policy check.

## Lint and test

```powershell
.\make.ps1 lint     # ruff check + ruff format --check
.\make.ps1 test     # pytest, integration tests skipped
.\make.ps1 format   # auto-fix
```

Tests never need Ollama or a GPU. Tests that use a real model are marked
`@pytest.mark.integration` and are skipped by default.

## Seed the demo data

One command loads everything the demo needs into a fresh database (about 15 s; safe to re-run):

```powershell
.\make.ps1 seed                      # or: uv run python scripts/seed_demo.py --reset
.\make.ps1 seed --cluster live       # re-cluster with Ollama instead of the saved clusters (~80 s)
```

Inside the Compose stack: `docker compose run --rm backend python /app/scripts/seed_demo.py --reset`.

| Step | What it does | Needs Ollama |
|---|---|---|
| data, scans | uses the committed synthetic CSVs and inspection images (regenerates if missing) | no |
| database | schema, equipment register, 491 work orders | no |
| clustering | failure modes from `clusters_fallback.json` (`--cluster live` to recompute) | live only |
| risk model | trains XGBoost on AI4I if `models/risk_xgb.json` is missing (~10 s) | no |
| manuals | indexes `data/docs/manuals` into ChromaDB | yes (warns if not) |
| inspections | OCR of `data/scans` into `inspections` (once the pipeline exists) | yes (warns if not) |
| verify | checks the planted story: P-101, C-203, E-302 are the top bad actors | no |

The run fails if a required step fails or the story doesn't verify. The data ends on 2026-11-13;
set `ANALYSIS_AS_OF=2026-11-14` in `.env` so the agent's "today" matches it.

## Run in containers

Four services, defined in `docker-compose.yml`:

| Service | Role | Network |
|---|---|---|
| `gateway` | nginx; the only host port (`127.0.0.1:8080`); proxies `/api` to the backend | `plant` + `edge` |
| `backend` | FastAPI, SQLite, analytics, agent, guard | `plant` |
| `chroma` | vector store server | `plant` |
| `ollama` | LLM, vision and embedding models on the GPU | `plant` |

`plant` is an internal-only Docker network, so `backend`, `chroma` and `ollama` have no route
off the machine. The gateway holds no data and only forwards requests.

Needs an NVIDIA GPU with Docker Desktop on the WSL2 backend. Check GPU passthrough with
`docker run --rm --gpus all ubuntu nvidia-smi`.

```powershell
# once: copy the weights your host Ollama already pulled into a Docker volume (about 90 s)
docker compose --profile setup run --rm model-copy
# ...or, if they are not on the host, download them instead (needs internet)
docker compose --profile setup run --rm model-pull

# every time (works offline after the first build)
docker compose up -d --build
```

**Quit the host Ollama app before every run** (system tray → Quit, or `ollama stop <model>`).
If it is holding a model in VRAM, the container falls back to CPU and drops below 1 token/s.
After asking one question, confirm the container is on the GPU:

```powershell
docker compose exec ollama ollama ps    # PROCESSOR column should say "100% GPU"
```

The gateway image builds the UI from `frontend/` (no host Node needed). By default the screens
whose backend exists are live and the rest show demo data; set `VITE_USE_MOCK=false` in `.env`
and rebuild to make everything live.

Prove the isolation from inside the backend container. The internal services must answer and
everything outside must be unreachable:

```powershell
docker compose exec backend python /app/scripts/check_isolation.py
```

Then open <http://127.0.0.1:8080/api/health>. Set `LLM_MODEL`, `VISION_MODEL` or `EMBED_MODEL`
in a `.env` file to change models; `EXTRA_MODELS` adds more to the pull. Build the backend with
`--build-arg UV_EXTRAS="--extra ocr"` to include PaddleOCR.

Running without Docker still works: with `CHROMA_HOST` unset the backend uses the embedded
Chroma store, and `OLLAMA_HOST` defaults to Ollama on the host.

## Data

- `data/raw/ai4i2020.csv`: [AI4I 2020 Predictive Maintenance dataset](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset)
  (UCI, CC BY 4.0), 10,000 rows. Committed so that setup needs no download.
- `data/synthetic/`: generated assets and work orders (`scripts/generate_synthetic.py`).
- `data/docs/`: manuals and SOPs. `data/scans/`: scanned inspection reports.

## Agent, RAG and documents

Set `OLLAMA_HOST` (default `http://localhost:11434`) if Ollama runs elsewhere. The analysis
window ends at the latest work-order date; pin it with `ANALYSIS_AS_OF=2026-11-14`.

```powershell
uv run python scripts/agent_cli.py check            # Ollama + models; --pull fetches missing ones
uv run python scripts/agent_cli.py ingest           # index data/docs/manuals into ChromaDB
uv run python scripts/agent_cli.py inspect-scans    # seeding: data/scans/* -> inspections (slow)
uv run python scripts/agent_cli.py search "seal failure misalignment"
uv run python scripts/agent_cli.py ask "Why does P-101 keep failing?" --demo-db
```

Agent tools (brief section 7): `get_asset_history`, `get_bad_actors`, `predict_risk`,
`search_manuals`, `read_inspection`, `generate_work_order`, `export_report`; at most 8 tool
calls per question. Calls to tools off the allow-list, or carrying a URL / e-mail, are blocked
by the `ToolGuard` hook (`app/agent/tools.py`) and reported as `blocked` events.

| Endpoint | Purpose |
|---|---|
| `POST /api/agent/ask` `{question, tag}` | SSE in the frontend contract: `step`, `token`, `done`, `blocked`, `error` |
| `POST /api/agent/chat` `{message, history}` | full agent event stream (`graph.EVENT_TYPES`) |
| `GET /api/agent/status` | Ollama, models and manual index readiness |
| `GET /api/assets/{tag}/inspection` | latest inspection (404 when none) |
| `POST /api/documents/work-order` `{tag}` | draft work order (.docx) |
| `POST /api/documents/bad-actor-report` | bad-actor report (.xlsx) |
| `GET /api/documents`, `GET /api/documents/{id}/download` | list / download generated files |

Real-model tests: `uv run pytest -m integration`. The manuals in `data/docs/manuals/` and the
vendor bulletin in `data/docs/demo_injection/` (prompt-injection demo) are synthetic.

## Commit policy

Commit messages and PR descriptions must not contain AI co-author trailers or "generated by"
attribution lines. This is enforced in two places:

- locally, by the `commit-msg` pre-commit hook (`scripts/check_no_ai_coauthor.py`)
- in CI, by `.github/workflows/commit-policy.yml`

## CI and branch protection

| Workflow | Runs on | Checks |
|---|---|---|
| `lint-test` | PRs, push to `main` | ruff check, ruff format, pytest; frontend lint and build |
| `commit-policy` | PRs | commit messages in the PR range and the PR body |

In GitHub, go to **Settings → Branches → Add rule for `main`** and enable
"Require status checks to pass". Mark `backend`, `frontend` and `no-ai-coauthor` as required.
Also enable "Require a pull request before merging".
