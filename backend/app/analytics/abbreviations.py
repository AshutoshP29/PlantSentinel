"""Normalise messy CMMS free text: lowercase, drop tags/punctuation, expand abbreviations."""

import re

# Multi-word phrases (mostly Hinglish filler) are replaced before single tokens.
PHRASES: dict[str, str] = {
    "aa raha hai": "",
    "aa gaya": "",
    "phir se": "again",
    "badh gaya": "increased",
    "check karo": "",
    "reset kiya": "reset",
    "o/l": "overload",
}

ABBREVIATIONS: dict[str, str] = {
    "lkg": "leakage",
    "brg": "bearing",
    "brgs": "bearings",
    "vib": "vibration",
    "temp": "temperature",
    "mech": "mechanical",
    "pr": "pressure",
    "repl": "replaced",
    "disch": "discharge",
    "lo": "lube oil",
    "de": "drive end",
    "nde": "non drive end",
    "dp": "differential pressure",
    "ir": "insulation resistance",
    "pm": "preventive maintenance",
    "hua": "",
    "hai": "",
    "karo": "",
    "kiya": "",
    "dekho": "",
}

TAG_RE = re.compile(r"\b[pcem]-?\d{3}\b")
NON_WORD_RE = re.compile(r"[^a-z0-9/ ]+")


def clean_text(text: str | None) -> str:
    """Return a normalised description suitable for embedding."""
    if not text:
        return ""
    t = TAG_RE.sub(" ", text.lower())
    for phrase, repl in PHRASES.items():
        t = t.replace(phrase, f" {repl} ")
    t = NON_WORD_RE.sub(" ", t)
    words = [ABBREVIATIONS.get(w, w) for w in t.split()]
    return " ".join(w for w in " ".join(words).split() if w)
