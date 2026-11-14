"""Generate the synthetic equipment register and messy work-order history.

Deterministic for a given --seed and --end-date. Template-based by default; --use-llm
optionally paraphrases background descriptions through the local Ollama server.

Outputs (in --out, default data/synthetic):
    assets.csv              equipment register (30 assets)
    work_orders.csv         ~500 messy work orders (the "CMMS export")
    work_orders_truth.csv   ground-truth failure mode per work order (for clustering eval only)

Planted story:
    P-101  4 mechanical-seal failures in the last 180 days, MTBF collapsing (~150 d -> ~50 d)
    C-203  bearing overheating, 3 events in the last 180 days
    E-302  tube fouling, 3 events in the last 180 days
Background events are capped at one per (asset, failure mode) inside the last 180 days so
no other asset accidentally becomes a bad actor.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_END = date(2026, 11, 14)
YEARS = 3
WINDOW_DAYS = 180

# --------------------------------------------------------------------------- assets

UNITS = ["CDU-1", "VDU", "FCC", "Hydrotreater", "Utilities", "Offsites"]
ASSET_GROUPS = {
    "pump": [f"P-{n}" for n in range(101, 116)],
    "compressor": [f"C-{n}" for n in range(201, 207)],
    "heat_exchanger": [f"E-{n}" for n in range(301, 306)],
    "motor": [f"M-{n}" for n in range(401, 405)],
}
FIXED_CRITICALITY = {"P-101": "A", "C-203": "A", "E-302": "B"}

# --------------------------------------------------------------------------- failure modes


@dataclass(frozen=True)
class Mode:
    name: str
    texts: tuple[str, ...]
    actions: tuple[str, ...]
    downtime: tuple[float, float]  # hours
    cost: tuple[int, int]  # INR


MODES: dict[str, Mode] = {
    m.name: m
    for m in [
        Mode(
            "Mechanical seal leakage",
            (
                "mech seal lkg",
                "seal leaking",
                "mechanical seal leakage observed",
                "seal leak hua",
                "gland side leakage from mech seal",
                "pump seal leaking, product dripping",
            ),
            ("replaced mech seal", "mechanical seal replaced", "seal changed", "new seal fitted"),
            (6, 14),
            (60_000, 140_000),
        ),
        Mode(
            "Pump bearing failure",
            (
                "brg noise DE side",
                "bearing noisy, high vib",
                "bearing failure on pump",
                "bearing damaged",
                "bearing sound aa raha hai",
            ),
            ("bearing replaced", "replaced DE brg", "new bearings fitted, greased"),
            (8, 20),
            (40_000, 110_000),
        ),
        Mode(
            "Cavitation",
            (
                "pump cavitating, low suction pressure",
                "cavitation noise, low flow",
                "low discharge pressure, cavitation suspected",
            ),
            ("suction strainer cleaned", "NPSH checked, strainer cleaned", "suction line flushed"),
            (2, 6),
            (8_000, 25_000),
        ),
        Mode(
            "Impeller wear",
            (
                "impeller worn, low head",
                "low flow, impeller eroded",
                "performance drop due to impeller wear",
            ),
            ("impeller replaced", "impeller and wear ring replaced"),
            (12, 30),
            (90_000, 220_000),
        ),
        Mode(
            "Compressor bearing overheating",
            (
                "brg temp high",
                "bearing overheating",
                "high bearing temperature alarm",
                "bearing temp badh gaya",
            ),
            ("lube oil changed, bearing checked", "bearing replaced", "oil cooler cleaned"),
            (10, 24),
            (120_000, 300_000),
        ),
        Mode(
            "Compressor valve failure",
            (
                "suction valve broken",
                "discharge valve plate cracked",
                "valve passing, low capacity",
            ),
            ("valve plate replaced", "valve overhauled", "suction valve replaced"),
            (8, 16),
            (70_000, 160_000),
        ),
        Mode(
            "High vibration",
            ("high vib trip", "vibration high on compressor", "vibration alarm, unit tripped"),
            (
                "foundation bolts tightened",
                "rotor balanced",
                "vibration analysis done, bolts tight",
            ),
            (4, 12),
            (30_000, 90_000),
        ),
        Mode(
            "Lube oil leak",
            ("lube oil leakage", "oil leak from LO cooler", "LO leakage at flange"),
            ("flange gasket replaced", "LO cooler gasket changed", "leak arrested, oil topped up"),
            (2, 6),
            (10_000, 30_000),
        ),
        Mode(
            "Tube leak",
            (
                "tube leakage",
                "tube leak found in hydro test",
                "shell side contamination, tube leak",
            ),
            ("leaking tubes plugged", "tube bundle retubed", "tubes plugged after hydrotest"),
            (24, 72),
            (150_000, 450_000),
        ),
        Mode(
            "Tube fouling",
            (
                "fouling, poor heat transfer",
                "high dp due to fouling",
                "outlet temp low, tubes fouled",
            ),
            ("bundle hydrojetted", "chemical cleaning done", "tubes cleaned"),
            (16, 40),
            (60_000, 150_000),
        ),
        Mode(
            "Gasket leak",
            ("gasket leakage at channel cover", "flange gasket leaking", "gasket leak hua"),
            ("gasket replaced", "bolts retorqued, gasket changed"),
            (4, 10),
            (15_000, 40_000),
        ),
        Mode(
            "Motor winding overheating",
            ("motor winding temp high", "motor overheating, tripped", "winding insulation IR low"),
            ("motor rewound", "motor sent for rewinding", "cooling fan cleaned, IR checked"),
            (12, 48),
            (80_000, 250_000),
        ),
        Mode(
            "Motor trip",
            ("motor tripped on overload", "o/l trip", "motor trip hua, reset kiya"),
            ("overload relay reset", "relay setting checked", "starter contacts cleaned"),
            (1, 4),
            (3_000, 15_000),
        ),
        Mode(
            "Routine maintenance",
            ("PM done", "routine PM, greasing done", "preventive maintenance completed", "PM ok"),
            ("no abnormality", "greasing done", "all parameters normal"),
            (1, 3),
            (2_000, 8_000),
        ),
    ]
}

MODES_BY_TYPE = {
    "pump": ["Mechanical seal leakage", "Pump bearing failure", "Cavitation", "Impeller wear"],
    "compressor": [
        "Compressor bearing overheating",
        "Compressor valve failure",
        "High vibration",
        "Lube oil leak",
    ],
    "heat_exchanger": ["Tube leak", "Tube fouling", "Gasket leak"],
    "motor": ["Motor winding overheating", "Motor trip"],
}
# Expected failure events per asset per year (background, before capping).
FAILURE_RATE = {"pump": 4.4, "compressor": 4.6, "heat_exchanger": 3.2, "motor": 3.6}
ROUTINE_RATE = 1.1

# Planted events: (tag, mode, days before end_date, description, action)
SEAL, CBRG, FOUL = "Mechanical seal leakage", "Compressor bearing overheating", "Tube fouling"
PLANTED: list[tuple[str, str, int, str, str]] = [
    # P-101: seal failures every ~150 days for 2 years...
    ("P-101", SEAL, 915, "mech seal lkg at P-101", "replaced mech seal"),
    ("P-101", SEAL, 765, "seal leaking, product dripping", "seal changed"),
    ("P-101", SEAL, 615, "P101 mechanical seal leakage", "new seal fitted"),
    ("P-101", SEAL, 465, "seal leak hua, replaced", "replaced mech seal"),
    ("P-101", SEAL, 315, "Mech seal leaking DE side", "seal changed"),
    # ...then 4 in the last 180 days, roughly every 50 days.
    ("P-101", SEAL, 165, "P-101 seal leaking again", "replaced mech seal"),
    (
        "P-101",
        SEAL,
        115,
        "mech seal lkg again, slight vib at coupling end",
        "mechanical seal replaced",
    ),
    ("P-101", SEAL, 60, "SEAL LEAK HUA PHIR SE P-101", "seal replaced again"),
    (
        "P-101",
        SEAL,
        12,
        "P-101 mech seal failed again within 2 months",
        "replaced mech seal, RCA requested",
    ),
    # C-203: bearing overheating getting worse.
    ("C-203", CBRG, 700, "brg temp high C-203 NDE", "oil cooler cleaned"),
    ("C-203", CBRG, 400, "bearing overheating", "lube oil changed"),
    ("C-203", CBRG, 150, "C203 brg temp high alarm", "lube oil changed"),
    ("C-203", CBRG, 95, "bearing overheating again", "bearing replaced"),
    ("C-203", CBRG, 30, "brg temp badh gaya, trip", "bearing checked"),
    # E-302: fouling.
    ("E-302", FOUL, 520, "high dp due to fouling", "bundle hydrojetted"),
    ("E-302", FOUL, 170, "E-302 outlet temp low, fouled", "chemical cleaning done"),
    ("E-302", FOUL, 100, "fouling again, poor heat transfer", "bundle hydrojetted"),
    ("E-302", FOUL, 40, "high DP E302 fouling", "tubes cleaned"),
]
PLANTED_PAIRS = {(tag, mode) for tag, mode, *_ in PLANTED}

# --------------------------------------------------------------------------- noise

ABBREVIATE = {
    "leakage": "lkg",
    "leaking": "lkg",
    "bearing": "brg",
    "vibration": "vib",
    "temperature": "temp",
    "mechanical": "mech",
    "pressure": "pr",
    "replaced": "repl",
    "discharge": "disch",
}
HINGLISH_SUFFIX = [" - check karo", " again aa gaya", " hua", " dekho"]


def add_noise(text: str, rng: random.Random, tag: str) -> str:
    """Make a clean template look like something typed into a CMMS at 3 a.m."""
    words = [
        ABBREVIATE[w.lower()] if w.lower() in ABBREVIATE and rng.random() < 0.4 else w
        for w in text.split()
    ]
    if rng.random() < 0.12:
        long_idx = [i for i, w in enumerate(words) if len(w) > 4 and w.isalpha()]
        if long_idx:
            i = rng.choice(long_idx)
            w = words[i]
            j = rng.randrange(len(w) - 1)
            words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2 :]
    out = " ".join(words)
    if rng.random() < 0.06:
        out += rng.choice(HINGLISH_SUFFIX)
    if rng.random() < 0.2:
        out = f"{rng.choice([tag, tag.replace('-', '')])} {out}"
    r = rng.random()
    if r < 0.15:
        out = out.upper()
    elif r < 0.35:
        out = out.lower()
    elif r < 0.55:
        out = out[0].upper() + out[1:]
    if rng.random() < 0.15:
        out += rng.choice([".", "..", " !!"])
    return out


# --------------------------------------------------------------------------- generation


def make_assets(rng: random.Random) -> pd.DataFrame:
    rows = []
    for asset_type, tags in ASSET_GROUPS.items():
        for tag in tags:
            crit = FIXED_CRITICALITY.get(tag) or rng.choices("ABC", weights=[3, 4, 3])[0]
            install = date(2008, 1, 1) + timedelta(days=rng.randrange(0, 12 * 365))
            rows.append(
                {
                    "tag": tag,
                    "type": asset_type,
                    "location": rng.choice(UNITS),
                    "criticality": crit,
                    "install_date": install.isoformat(),
                }
            )
    return pd.DataFrame(rows)


def _event(
    tag: str, mode: str, day: date, desc: str, action: str, rng: random.Random, **flags: bool
) -> dict:
    m = MODES[mode]
    return {
        "tag": tag,
        "date": day,
        "description": desc,
        "action_taken": action,
        "downtime_hrs": round(rng.uniform(*m.downtime), 1),
        "cost_inr": round(rng.uniform(*m.cost), -2),
        "true_mode": mode,
        "planted": flags.get("planted", False),
        "duplicate": flags.get("duplicate", False),
    }


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth; fine for small lambda.
    limit, k, p = pow(2.718281828459045, -lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def make_events(assets: pd.DataFrame, rng: random.Random, end: date) -> list[dict]:
    start = end - timedelta(days=YEARS * 365)
    window_start = end - timedelta(days=WINDOW_DAYS)
    span = (end - start).days
    events: list[dict] = []

    for tag, asset_type in zip(assets["tag"], assets["type"], strict=True):
        modes = [m for m in MODES_BY_TYPE[asset_type] if (tag, m) not in PLANTED_PAIRS]
        n_fail = _poisson(rng, FAILURE_RATE[asset_type] * YEARS)
        n_pm = _poisson(rng, ROUTINE_RATE * YEARS)
        picks = [rng.choice(modes) for _ in range(n_fail)] + ["Routine maintenance"] * n_pm
        seen_in_window: set[str] = set()
        for mode in picks:
            day = start + timedelta(days=rng.randrange(span))
            if day >= window_start:
                if mode in seen_in_window and mode != "Routine maintenance":
                    continue  # cap: keep background quiet inside the bad-actor window
                seen_in_window.add(mode)
            m = MODES[mode]
            desc = add_noise(rng.choice(m.texts), rng, tag)
            events.append(_event(tag, mode, day, desc, rng.choice(m.actions), rng))
            # Occasional duplicate entry with different wording (outside the window only).
            if day < window_start - timedelta(days=2) and rng.random() < 0.04:
                dup = add_noise(rng.choice(m.texts), rng, tag)
                dup_day = day + timedelta(days=rng.choice([0, 1]))
                events.append(
                    _event(tag, mode, dup_day, dup, rng.choice(m.actions), rng, duplicate=True)
                )

    for tag, mode, days_ago, desc, action in PLANTED:
        events.append(
            _event(tag, mode, end - timedelta(days=days_ago), desc, action, rng, planted=True)
        )
    return events


def paraphrase_with_llm(texts: list[str], seed: int) -> list[str]:
    """Paraphrase descriptions via local Ollama. Only used with --use-llm."""
    import httpx

    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import get_settings

    settings = get_settings()
    out = []
    for t in texts:
        prompt = (
            "Rewrite this plant maintenance work-order note the way a busy technician would "
            "type it. Keep the meaning and equipment tag, keep it under 12 words, reply with "
            f"the note only.\nNote: {t}"
        )
        r = httpx.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": settings.llm_model,
                "prompt": prompt,
                "stream": False,
                "options": {"seed": seed, "temperature": 0.8},
            },
            timeout=60,
        )
        r.raise_for_status()
        out.append(r.json()["response"].strip().strip('"') or t)
    return out


def generate(seed: int = 42, end: date = DEFAULT_END) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (assets, work_orders_with_truth). Pure and deterministic."""
    rng = random.Random(seed)
    assets = make_assets(rng)
    wo = pd.DataFrame(make_events(assets, rng, end))
    wo = wo.sort_values(["date", "tag", "description"], kind="stable").reset_index(drop=True)
    wo.insert(0, "id", [f"WO-{i:04d}" for i in range(1, len(wo) + 1)])
    wo["date"] = wo["date"].map(date.isoformat)
    return assets, wo


WO_COLUMNS = ["id", "tag", "date", "description", "action_taken", "downtime_hrs", "cost_inr"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate synthetic assets and work orders.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--end-date", type=date.fromisoformat, default=DEFAULT_END)
    p.add_argument("--out", type=Path, default=ROOT / "data" / "synthetic")
    p.add_argument("--use-llm", action="store_true", help="paraphrase background text via Ollama")
    args = p.parse_args(argv)

    assets, wo = generate(args.seed, args.end_date)
    if args.use_llm:
        mask = ~wo["planted"]
        wo.loc[mask, "description"] = paraphrase_with_llm(
            wo.loc[mask, "description"].tolist(), args.seed
        )

    args.out.mkdir(parents=True, exist_ok=True)
    assets.to_csv(args.out / "assets.csv", index=False)
    wo[WO_COLUMNS].to_csv(args.out / "work_orders.csv", index=False)
    wo[["id", "true_mode", "planted", "duplicate"]].to_csv(
        args.out / "work_orders_truth.csv", index=False
    )

    print(f"assets: {len(assets)}  work orders: {len(wo)}  -> {args.out}")
    window = wo[wo["date"] >= (args.end_date - timedelta(days=WINDOW_DAYS)).isoformat()]
    top = window.groupby(["tag", "true_mode"]).size().sort_values(ascending=False).head(5)
    print("top (tag, mode) counts in last 180 days:")
    print(top.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
