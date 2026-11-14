"""Fail if a commit message or PR body carries AI co-author / attribution lines.

Usage:
    python scripts/check_no_ai_coauthor.py .git/COMMIT_EDITMSG      # commit-msg hook
    python scripts/check_no_ai_coauthor.py --range BASE..HEAD       # CI
    python scripts/check_no_ai_coauthor.py --range A..B --text-env PR_BODY

Standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterable

PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*co-authored-by:.*(claude|anthropic)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"noreply@anthropic\.com", re.IGNORECASE),
    re.compile(r"generated with \[?claude code", re.IGNORECASE),
]


def find_violations(text: str) -> list[str]:
    """Return every line of `text` that matches a forbidden pattern."""
    hits: list[str] = []
    for line in text.splitlines():
        if any(p.search(line) for p in PATTERNS):
            hits.append(line.strip())
    return hits


def strip_git_comments(text: str) -> str:
    """Drop '#' comment lines that git removes from the final commit message."""
    return "\n".join(line for line in text.splitlines() if not line.startswith("#"))


def commits_in_range(rev_range: str) -> Iterable[tuple[str, str]]:
    """Yield (sha, message) for each commit in a git revision range."""
    out = subprocess.run(
        ["git", "log", "--format=%H%x00%B%x1e", rev_range],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    for record in out.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, _, message = record.partition("\x00")
        yield sha.strip(), message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("msg_file", nargs="?", help="commit message file (commit-msg hook)")
    parser.add_argument("--range", dest="rev_range", help="git revision range BASE..HEAD")
    parser.add_argument("--text-env", help="env var holding extra text to check (e.g. PR body)")
    args = parser.parse_args(argv)

    if not (args.msg_file or args.rev_range or args.text_env):
        parser.error("give a message file, --range, or --text-env")

    failed = False

    if args.msg_file:
        with open(args.msg_file, encoding="utf-8") as f:
            text = strip_git_comments(f.read())
        for line in find_violations(text):
            print(f"commit message: {line}")
            failed = True

    if args.rev_range:
        for sha, message in commits_in_range(args.rev_range):
            for line in find_violations(message):
                print(f"{sha}: {line}")
                failed = True

    if args.text_env:
        for line in find_violations(os.environ.get(args.text_env, "")):
            print(f"${args.text_env}: {line}")
            failed = True

    if failed:
        print("ERROR: AI co-author/attribution lines are not allowed. Remove them and retry.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
