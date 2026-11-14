import subprocess
from pathlib import Path

import pytest

import check_no_ai_coauthor as checker

BAD_MESSAGES = [
    "fix: thing\n\nCo-authored-by: Claude <noreply@anthropic.com>",
    "fix\n\n  co-authored-by: Someone (Anthropic)",
    "feat: x\n\nCO-AUTHORED-BY: claude opus",
    "docs\n\ncontact noreply@ANTHROPIC.com",
    "pr body\n\nGenerated with [Claude Code](https://claude.com/claude-code)",
    "generated with claude code",
]

GOOD_MESSAGES = [
    "feat: add bad-actor scoring",
    "fix\n\nCo-authored-by: Priya <priya@example.com>",
    "docs: mention claude in a sentence about tooling",
    "",
]


@pytest.mark.parametrize("msg", BAD_MESSAGES)
def test_find_violations_flags_bad(msg: str) -> None:
    assert checker.find_violations(msg)


@pytest.mark.parametrize("msg", GOOD_MESSAGES)
def test_find_violations_allows_good(msg: str) -> None:
    assert checker.find_violations(msg) == []


def test_msg_file_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text(BAD_MESSAGES[0], encoding="utf-8")
    assert checker.main([str(bad)]) == 1
    assert "Co-authored-by: Claude" in capsys.readouterr().out

    good = tmp_path / "good.txt"
    good.write_text("feat: ok\n# Generated with Claude Code (git comment, stripped)\n")
    assert checker.main([str(good)]) == 0


def test_text_env_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_BODY", "Summary\n\nGenerated with Claude Code")
    assert checker.main(["--text-env", "PR_BODY"]) == 1
    monkeypatch.setenv("PR_BODY", "Summary only")
    assert checker.main(["--text-env", "PR_BODY"]) == 0
    monkeypatch.delenv("PR_BODY")
    assert checker.main(["--text-env", "PR_BODY"]) == 0


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_range_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "clean commit")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "x\n\nCo-authored-by: Claude <a@b.c>")
    bad_sha = _git(repo, "rev-parse", "HEAD")

    monkeypatch.chdir(repo)
    assert checker.main(["--range", f"{base}..HEAD"]) == 1
    assert bad_sha in capsys.readouterr().out
    assert checker.main(["--range", f"{base}..HEAD~1"]) == 0


def test_requires_some_input() -> None:
    with pytest.raises(SystemExit):
        checker.main([])
