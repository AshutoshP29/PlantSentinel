"""Redaction of secrets and personal data before anything is stored.

Used for every audit-log row (guard/audit.py) and for all ingested free text: work-order
descriptions and actions, and scanned inspection reports. Standard library only, so the
ingestion path stays light. Pattern-based: it catches secrets, keys, e-mail addresses, Indian
phone numbers and Aadhaar-style ID numbers, not personal names.
"""

from __future__ import annotations

import re

# What must not sit in an audit table in clear text. Order matters: specific before generic.
REDACTIONS: list[tuple[str, re.Pattern[str]]] = [
    (
        "secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization)\b"
            r"(\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;}]+)"
        ),
    ),
    ("key", re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("phone", re.compile(r"(?<![\w.])(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\w.])")),
    ("id", re.compile(r"(?<![\w.])\d{4}[\s-]\d{4}[\s-]\d{4}(?![\w.])")),  # Aadhaar-style
]
REDACTED_MARK = "[REDACTED:"


def redact(text: str) -> tuple[str, int]:
    """Replace secrets and personal data with `[REDACTED:kind]`. Returns (text, how many)."""
    total = 0
    for kind, pattern in REDACTIONS:
        if kind == "secret":
            text, n = pattern.subn(rf"\1\2{REDACTED_MARK}secret]", text)
        else:
            text, n = pattern.subn(f"{REDACTED_MARK}{kind}]", text)
        total += n
    return text, total


def redact_text(text: str) -> str:
    """`redact` without the count, for callers that only need the clean text."""
    return redact(text)[0]


def redact_value(value: object) -> tuple[object, int]:
    """Redact every string inside nested dicts and lists. Returns (value, how many)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        total, out = 0, {}
        for k, v in value.items():
            out[k], n = redact_value(v)
            total += n
        return out, total
    if isinstance(value, list):
        total, items = 0, []
        for v in value:
            item, n = redact_value(v)
            items.append(item)
            total += n
        return items, total
    return value, 0
