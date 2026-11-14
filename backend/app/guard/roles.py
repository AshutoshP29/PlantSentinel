"""Role permissions (spec section 11): technician = view, ask; engineer = also export, generate.

The role comes from the `X-Role` header the UI sends. A missing or unknown role gets the least
privilege (technician). Enforced in two places:
  * the agent: a technician is only offered the tools it may use, and any other call is blocked
    by the graph like every policy violation (audited, shown as blocked);
  * the document endpoints: 403 for roles without the permission.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Header, HTTPException

from app.agent.tools import TOOL_SPECS

DEFAULT_ROLE = "technician"
PERMISSIONS: dict[str, frozenset[str]] = {
    "engineer": frozenset({"view", "ask", "export", "generate"}),
    "technician": frozenset({"view", "ask"}),
}
# Tools that need more than "ask".
TOOL_PERMISSION = {"generate_work_order": "generate", "export_report": "export"}


def resolve_role(header: str | None) -> str:
    role = (header or "").strip().lower()
    return role if role in PERMISSIONS else DEFAULT_ROLE


def can(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, PERMISSIONS[DEFAULT_ROLE])


def allowed_tools(role: str) -> list[str]:
    """Agent tools this role may call, in registry order."""
    return [
        name
        for name, *_ in TOOL_SPECS
        if name not in TOOL_PERMISSION or can(role, TOOL_PERMISSION[name])
    ]


def require(permission: str) -> Callable[[str | None], str]:
    """FastAPI dependency: the caller's role, or 403 if it lacks `permission`."""

    def dependency(x_role: str | None = Header(None)) -> str:
        role = resolve_role(x_role)
        if not can(role, permission):
            raise HTTPException(
                403, f"The {role} role can't {permission} documents; an engineer can."
            )
        return role

    return dependency
