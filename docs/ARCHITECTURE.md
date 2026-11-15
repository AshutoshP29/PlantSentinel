# Architecture

PlantSentinel is a single-machine system: one laptop runs the model server, the vector store,
the API and the UI, and nothing it processes leaves that machine. This document explains how
the parts fit, how a request flows through them, how privacy is enforced, and why the main
design choices were made. For setup and commands see the [README](../README.md); for the
datasets and the planted story see [DATA.md](DATA.md).

## Components

```
                       ┌──────────────────────────── network "edge" ───────────────┐
 browser ── HTTP ────► │ gateway  nginx · serves the built UI · proxies /api       │
 127.0.0.1:8080        └───────────────┬───────────────────────────────────────────┘
                       ┌───────────────▼──────────── network "plant" (internal) ───┐
                       │ backend  FastAPI                                          │
                       │   api/        routers (REST + server-sent events)         │
                       │   analytics/  clustering · bad actors · risk · dashboard  │
                       │   agent/      LangGraph loop · tools · RAG · inspections  │
                       │   guard/      allow-list · roles · audit · redaction      │
                       │   privacy/    connection monitor · injection drill        │
                       │   ingestion/  CSV/XLSX work orders · scan seeding         │
                       │   docgen/     work order .docx · bad-actor report .xlsx   │
                       │   SQLite (app_state volume)                               │
                       │        │                         │                        │
                       │        ▼                         ▼                        │
                       │ ollama  LLM · vision · embeddings   chroma  manual chunks  │
                       │         (GPU, ollama_models volume)  (chroma_data volume)  │
                       └───────────────────────────────────────────────────────────┘
```

| Service | Image / build | Networks | State |
|---|---|---|---|
| `gateway` | `frontend/Dockerfile` (Node build → nginx) + `deploy/gateway/nginx.conf` | `edge`, `plant` | none |
| `backend` | `backend/Dockerfile` (python:3.12-slim + uv) | `plant` | `app_state` (SQLite, generated documents), `./data`, `./models` |
| `ollama` | `ollama/ollama:0.40.16`, GPU | `plant` | `ollama_models` |
| `chroma` | `chromadb/chroma` | `plant` | `chroma_data` |
| `model-copy`, `model-pull` | one-off setup profiles | none / `edge` | fill `ollama_models` |

Only the gateway publishes a port, and only on loopback. `plant` is `internal: true`: the
services on it can reach each other but not the internet, a raw IP or the host.

## Main flows

**Seeding** (`scripts/seed_demo.py`, run once): synthetic CSVs → `assets` and `work_orders`
→ failure modes (saved clustering, or live with `--cluster live`) → risk model trained if
missing → manuals chunked and embedded into Chroma → scans transcribed (vision model) and
structured (text model) into `inspections` → the planted story is verified. Slow model work
happens here, never during the demo.

**Dashboard** (`api/analytics.py`): each request reads SQLite and computes in pandas.
Windows end at `ANALYSIS_AS_OF` or the latest work order, never the wall clock, so the
"last 180 days" stays stable however long after seeding the demo runs.

**Asking the agent** (`POST /api/agent/ask`, server-sent events):

```
question ─► role from X-Role ─► tools allowed for that role
        ─► LangGraph loop (max 8 tool calls)
             agent node: local LLM chooses tool calls
             tools node: guard.check → execute → audit row → event to the UI
             checklist: a "why does X fail" answer must rest on history, inspection, manuals
        ─► answer: citations normalised ([INSP-004], [S2], [WO-0486]), streamed as tokens
```

The UI receives `step`, `token`, `done` (with the citation list), `blocked` and `error`
events (`agent/frontend_events.py` adapts the graph's internal events to this contract).

**Documents**: `generate_work_order` builds a `.docx` from the grounded recommendation
(manual passages plus history); `export_report` writes the bad-actor `.xlsx`. Both are
registered in `docgen/documents.py` and downloadable from `/api/documents`.

## Privacy and security

Three independent layers, so one failing is not enough to leak data:

1. **Network isolation.** The backend has no route off the machine.
   `scripts/check_isolation.py` proves it from inside the container: Ollama and Chroma
   reachable; `example.com`, `1.1.1.1` and `host.docker.internal` blocked.
2. **The guard.** Every tool call passes `guard.check` before it runs:
   - only the seven registered tools exist; any other name is blocked;
   - arguments carrying a URL or e-mail address are blocked;
   - the user's role limits the tools offered (`guard/roles.py`); a call outside the role's
     set is blocked by the graph;
   - every call, allowed or not, is written to `audit_log` (user, role, input, output,
     status), with secrets, e-mails, phone numbers and ID numbers redacted; blocked calls also
     go to `blocked_attempts` with their target and the document that asked for them.
3. **Proof on screen.** `privacy/network.py` reads the backend's live sockets from the kernel
   (it never probes the network) and reports external connections, normally 0. The injection
   drill (`privacy/injection.py`) finds the hidden instruction in the poisoned vendor bulletin
   and submits exactly that call to the guard. It's deterministic and needs no model: it proves
   the guard holds even if the model were fully fooled.

Text returned by tools is treated as data: the system prompt says so, and manuals are indexed
separately from the injection folder.

### Roles

| Role (`X-Role`) | View, ask | Generate work orders | Export reports |
|---|---|---|---|
| `technician` (also: missing or unknown) | yes | no | no |
| `engineer` | yes | yes | yes |

## Data model (SQLite)

```
assets(tag PK, type, location, criticality A|B|C, install_date)
failure_modes(id PK, name UNIQUE, description)
work_orders(id PK, tag → assets, date, description, description_clean, action_taken,
            downtime_hrs, cost_inr, failure_mode_id → failure_modes)
inspections(id PK, tag → assets, date, file_path, raw_text, extracted_json)
audit_log(id PK, ts, user, role, action, tool, input, output, status allowed|blocked|error)
blocked_attempts(id PK, ts, user, tool, target, source, reason, audit_id → audit_log)
```

Vectors live in Chroma (collection `manuals`, cosine), one chunk per page section, with the
document, page and section as metadata for citations. Trained artefacts live in `models/`
(`risk_xgb.json`, `risk_meta.json`, `metrics.json`).

## Key design decisions

| Decision | Why | Evidence |
|---|---|---|
| Ollama in a container on an internal network, not on the host | An internal network also cuts the route to the host, so the model server must sit inside it; the proof then holds with Wi-Fi on | `check_isolation.py`: ISOLATED |
| Models in a named volume, copied once | A Windows bind mount cold-loads in ~110 s; the volume in ~9 s | measured on the demo laptop |
| `qwen2.5:7b-instruct-q3_K_M` as default LLM | Fits entirely in 6 GB at 39–41 tok/s and keeps the 7B's tool choices; the q4 model spills 18% to CPU | `scripts/benchmark_models.py` |
| Vision model only transcribes; the text LLM extracts findings | `qwen2.5vl:3b` returned empty JSON when asked to structure text; findings and dates are also parsed from the transcript as a fallback | 4/4 scans, 5/5 P-101 findings |
| HDBSCAN + centroid merge + LLM naming with a synonym pass | Plain HDBSCAN split one failure by wording (29 clusters, ARI 0.39) | ARI 0.93 against ground truth |
| Bad-actor score is plain arithmetic | Every number traces to work-order IDs; judges and engineers can check it | exactly the 3 planted assets flagged |
| Risk threshold tuned on a validation split | Test metrics stay honest at a 3.4% failure rate | F1 0.84, ROC-AUC 0.975 on held-out data |
| Checklist and citation rewrite around the agent | A small model may answer early or cite a tool name; the code enforces evidence and the spec's citation format | rehearsal 3/3 |
| Deterministic injection drill | A drill that waits for the model to misbehave proves little either way | blocked in under 2 s, every run |
| Windows anchored to the data, not the clock | The planted story must hold on demo day and after | `ANALYSIS_AS_OF` / latest work order |

## Known gaps

- **PII redaction on ingest is not wired.** `ingest_work_orders(..., redact=)` accepts a
  redactor, but no caller passes one; redaction currently runs on audit-log entries only, and
  it uses regular expressions rather than Presidio.
- **No real authentication.** The role comes from a header the UI sets (spec §11 asks for no
  more). Sign-in and user management in the UI are local to the browser.
- **`DELETE /api/data`** (the UI's reset button) has no backend route.
- **Live upload of scans** has no route; scans are read at seeding time.
- **Risk operating conditions are mapped.** AI4I is a lab dataset; each asset is given one
  held-out AI4I row as its current condition, chosen so the story assets are high risk.
