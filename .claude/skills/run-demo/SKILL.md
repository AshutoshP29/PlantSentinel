---
name: run-demo
description: Bring up the PlantSentinel stack on the demo laptop, seed it, prove it works offline, and recover from common failures. Use when asked to run, start, seed, rehearse or check the demo, or when the demo misbehaves (slow answers, missing inspections, 403s, Docker errors).
---

# Run the PlantSentinel demo

Everything runs from the repository root on Windows (PowerShell). In Git Bash, prefix
`docker compose exec ... /app/...` commands with `MSYS_NO_PATHCONV=1`.

## 1. First time on a machine

1. Models on the host (needs internet once):
   `ollama pull qwen2.5:7b-instruct-q3_K_M`, `ollama pull qwen2.5vl:3b`,
   `ollama pull nomic-embed-text`.
2. `.\make.ps1 setup`
3. Copy weights into the Docker volume (offline, ~3 min):
   `docker compose --profile setup run --rm model-copy`.
   If it reports no models found, `OLLAMA_MODELS` points elsewhere: set
   `$env:OLLAMA_MODELS_SRC` to that folder and re-run.
4. Build once with internet: `docker compose up -d --build`.

## 2. Every run

1. Quit the Ollama app in the system tray (it holds the GPU).
2. Start Docker Desktop if `docker info` fails.
3. `docker compose up -d`; wait until `docker compose ps` shows `backend` and `ollama` healthy.
4. Seed (first run, or to reset):
   `docker compose exec backend python /app/scripts/seed_demo.py --reset`
   Expect `[7/8] inspections ok 4 scans: 4 added` and `[8/8] verify ok top 3 = P-101, C-203, E-302`.
5. Warm the model and check everything: `.\make.ps1 demo-check` → `DEMO READY`.
6. For the offline proof, switch Wi-Fi off and run `.\make.ps1 offline-check` →
   `ISOLATED` then `DEMO READY`.

UI: http://127.0.0.1:8080. Demo question: "Why does P-101 keep failing and what should we do?"

## 3. Checks and what they mean

| Command | Passes when |
|---|---|
| `docker compose exec backend python /app/scripts/check_isolation.py` | Ollama and Chroma reachable; internet, raw IP and host blocked |
| `uv run --offline python scripts/demo_check.py` | stack, dashboard, asset detail, agent, work order, privacy all PASS |
| `docker compose exec backend python /app/scripts/agent_cli.py rehearse -n 3` | 3/3 runs: history, INSP-004 cited, 0.05 mm manual passage, `.docx` |
| `docker compose exec ollama ollama ps` | the loaded model shows `100% GPU` |

## 4. Recovery

| Symptom | Fix |
|---|---|
| Answers under 1 token/s | Host Ollama holds VRAM: quit it, `docker compose restart ollama` |
| First answer ~50 s | Cold model; run `demo-check` once before presenting |
| Seed step 7 warns | Vision or text model missing from the volume: pull on the host, re-run `model-copy` |
| Inspections stored with no findings | Old backend image: `docker compose build backend` and re-seed with `--reset` |
| `docker compose build` fails on a download | Network dropped: re-run (uv cache keeps progress) |
| Work order returns 403 | The signed-in role is a technician; use an engineer role |
| Risk endpoint 503 | Model not trained: re-run the seed |
| Docker "cannot find the file specified" | Docker Desktop is not running |

Report results with the actual command output. Don't claim the demo is ready unless
`demo-check` printed `DEMO READY`.
