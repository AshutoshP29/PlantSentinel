import io
import json

import pytest

import demo_check


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_sse_yields_json_data_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b'event: x\ndata: {"type": "step"}\n\n: comment\ndata: {"type": "done"}\n\ndata:\n'
    monkeypatch.setattr(demo_check.urllib.request, "urlopen", lambda req, timeout: FakeResp(body))
    assert [e["type"] for e in demo_check.sse("http://x", "/p", {})] == ["step", "done"]


def test_requests_carry_engineer_role(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake(req, timeout):
        seen.update(dict(req.header_items()), url=req.full_url, method=req.get_method())
        return FakeResp(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(demo_check.urllib.request, "urlopen", fake)
    assert demo_check.post_json("http://h", "/api/x", {"a": 1}) == {"ok": True}
    assert seen["X-role"] == "engineer" and seen["method"] == "POST"
    assert seen["url"] == "http://h/api/x"


def test_unreachable_stack_fails_every_beat(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo_check.main(["--base", "http://127.0.0.1:9", "--skip-agent"]) == 1
    out = capsys.readouterr().out
    assert out.count("FAIL") == 5 and "SKIP  ask agent" in out and "beat(s) failed" in out
