"""Benchmark candidate LLMs on this machine: GPU fit, speed, tool calling, JSON naming.

    uv run python scripts/benchmark_models.py qwen2.5:3b-instruct qwen2.5:7b-instruct

Needs Ollama running. Unloads each model afterwards so runs don't interfere.
"""

import json
import sys
import time

import httpx

HOST = "http://localhost:11434"
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {"tag": {"type": "string", "description": "Asset tag, e.g. P-101"}},
                "required": ["tag"],
            },
        },
    }
    for name, desc in [
        ("get_asset_history", "Work orders, failure modes and MTBF summary for one asset."),
        ("predict_risk", "Current failure-risk score and top reasons for one asset."),
        ("read_inspection", "Structured findings from the latest inspection report of an asset."),
    ]
]
SYSTEM = "You are a reliability engineer. Use tools to gather facts. Never invent data."
QUESTION = "Why does P-101 keep failing and what should we do?"
NAMING = (
    "These maintenance notes describe the same failure:\n- mech seal leakage\n"
    "- seal leaking product dripping\n- mechanical seal leak replaced\n"
    'Reply with JSON only: {"name": "<2-4 word failure mode>", "description": "<one sentence>"}'
)


def chat(model: str, body: dict) -> tuple[dict, float]:
    t = time.perf_counter()
    r = httpx.post(
        f"{HOST}/api/chat",
        json={"model": model, "stream": False, "options": {"temperature": 0}, **body},
        timeout=600,
    )
    r.raise_for_status()
    return r.json(), time.perf_counter() - t


def processor(model: str) -> str:
    for m in httpx.get(f"{HOST}/api/ps").json().get("models", []):
        if m["name"] == model:
            vram, size = m.get("size_vram", 0), m.get("size", 1)
            return f"{100 * vram / size:.0f}% GPU ({size / 1e9:.1f} GB)"
    return "not loaded"


def bench(model: str) -> dict:
    out = {"model": model}
    _, out["cold_load_s"] = chat(model, {"messages": [{"role": "user", "content": "Say OK."}]})
    out["gpu"] = processor(model)

    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": QUESTION}]
    tools_ok = 0
    for _ in range(3):
        resp, out["tool_call_s"] = chat(model, {"messages": msgs, "tools": TOOLS})
        calls = resp["message"].get("tool_calls") or []
        tools_ok += any(c["function"]["arguments"].get("tag") == "P-101" for c in calls)
    out["tool_call_ok"] = f"{tools_ok}/3"
    out["tool_calls"] = [c["function"]["name"] for c in calls]

    resp, _ = chat(model, {"messages": [{"role": "user", "content": NAMING}], "format": "json"})
    out["naming"] = json.loads(resp["message"]["content"]).get("name")

    long = "Explain in about 150 words how shaft misalignment damages a pump mechanical seal."
    resp, _ = chat(model, {"messages": [{"role": "user", "content": long}]})
    out["tokens_per_s"] = round(resp["eval_count"] / (resp["eval_duration"] / 1e9), 1)
    out["answer_150w_s"] = round(resp["total_duration"] / 1e9, 1)

    httpx.post(f"{HOST}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)
    out["cold_load_s"] = round(out["cold_load_s"], 1)
    out["tool_call_s"] = round(out["tool_call_s"], 1)
    return out


if __name__ == "__main__":
    for m in sys.argv[1:]:
        print(json.dumps(bench(m)), flush=True)
