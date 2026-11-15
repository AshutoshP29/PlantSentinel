import pytest
from fastapi.testclient import TestClient

from app.agent.tools import TOOL_NAMES
from app.guard import roles
from app.main import app


@pytest.mark.parametrize(
    ("header", "role"),
    [
        ("engineer", "engineer"),
        (" ENGINEER ", "engineer"),
        ("technician", "technician"),
        (None, "technician"),
        ("", "technician"),
        ("admin", "technician"),
    ],
)
def test_resolve_role_defaults_to_least_privilege(header: str | None, role: str) -> None:
    assert roles.resolve_role(header) == role


def test_permissions_match_the_spec() -> None:
    assert roles.can("engineer", "generate") and roles.can("engineer", "export")
    assert roles.can("technician", "ask") and roles.can("technician", "view")
    assert not roles.can("technician", "generate") and not roles.can("technician", "export")
    assert roles.can("engineer", "manage") and not roles.can("technician", "manage")
    assert roles.allowed_tools("engineer") == TOOL_NAMES
    tech = roles.allowed_tools("technician")
    assert "generate_work_order" not in tech and "export_report" not in tech
    assert {"get_asset_history", "read_inspection", "search_manuals", "predict_risk"} <= set(tech)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/documents/work-order", {"tag": "P-101"}),
        ("/api/documents/bad-actor-report", {}),
    ],
)
@pytest.mark.parametrize("headers", [{}, {"X-Role": "technician"}, {"X-Role": "admin"}])
def test_document_endpoints_refuse_non_engineers(path: str, body: dict, headers: dict) -> None:
    r = TestClient(app).post(path, json=body, headers=headers)
    assert r.status_code == 403
    assert "an engineer can" in r.json()["detail"]
