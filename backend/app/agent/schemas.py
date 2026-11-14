"""Pydantic schemas for tool inputs and the structured maintenance recommendation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Priority = Literal["Emergency", "High", "Medium", "Low"]

# --------------------------------------------------------------------------- tool inputs


class SearchManualsInput(BaseModel):
    query: str = Field(
        min_length=3,
        max_length=300,
        description="What to look up in the technical manuals, e.g. 'causes of repeated "
        "mechanical seal failure'.",
    )
    equipment_type: Literal["pump", "compressor", "heat_exchanger", "motor"] | None = Field(
        None, description="Optional: restrict to manuals for this equipment type."
    )


class TagInput(BaseModel):
    tag: str = Field(description="Equipment tag, e.g. P-101.")


class AssetHistoryInput(TagInput):
    keywords: list[str] | None = Field(
        None,
        description="Optional words to focus the failure statistics on, e.g. ['seal'] or "
        "['overheat', 'temp']. Leave empty for all work orders.",
    )
    window_days: int | None = Field(
        None, ge=30, le=1095, description="Recent window in days (default 180)."
    )
    limit: int = Field(15, ge=1, le=100, description="How many recent work orders to list.")


class InspectionInput(BaseModel):
    tag: str | None = Field(None, description="Equipment tag: returns its latest inspection.")
    inspection_id: str | None = Field(
        None, description="A specific inspection id, e.g. INSP-P101-20261102."
    )

    @model_validator(mode="after")
    def _one_of(self) -> InspectionInput:
        if not (self.tag or self.inspection_id):
            raise ValueError("give a tag or an inspection_id")
        return self


class ExportReportInput(BaseModel):
    type: Literal["bad_actors"] = Field(
        "bad_actors", description="Report type. Only 'bad_actors' (.xlsx) is available."
    )
    top_n: int = Field(20, ge=1, le=100)


class BadActorInput(BaseModel):
    tag: str | None = Field(None, description="Optional tag to report the rank of.")
    top_n: int = Field(5, ge=1, le=30)


class RecommendInput(TagInput):
    issue: str = Field(
        min_length=3, max_length=300, description="The problem to address, in plain words."
    )


class WorkOrderInput(TagInput):
    issue: str = Field(min_length=3, max_length=300, description="Reported issue / problem.")
    priority: Priority | None = Field(
        None, description="Optional override. Normally taken from the recommendation."
    )


# --------------------------------------------------------------------------- recommendation


class Sourced(BaseModel):
    sources: list[str] = Field(
        default_factory=list, description="Manual refs like S1, or work order ids like WO-0012."
    )

    @field_validator("sources", mode="before")
    @classmethod
    def _normalise_refs(cls, v: object) -> list[str]:
        items = [v] if isinstance(v, str) else list(v or [])  # type: ignore[call-overload]
        return [str(s).strip().strip("[]").upper() for s in items if str(s).strip()]


class Cause(Sourced):
    cause: str
    evidence: str = Field(description="Facts from history or manuals that support this cause.")


class Action(Sourced):
    action: str


class Recommendation(BaseModel):
    summary: str = Field(description="Two or three sentences: what is wrong and what to do.")
    probable_causes: list[Cause] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    materials: list[Action] = Field(
        default_factory=list, description="Parts/materials named in the manuals."
    )
    safety: list[Action] = Field(
        default_factory=list, description="Safety precautions stated in the manuals."
    )
    estimated_duration: Action | None = Field(
        None, description="Duration as stated in the manuals, with its source."
    )
    priority: Priority = "Medium"
    priority_reason: str = ""
