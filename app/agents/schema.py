"""Structured output schema for the review LLM call.

Kept separate so the eval framework (Phase 4) can import it without pulling
in the whole graph, and so prompt/schema versions can evolve independently.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IssueType = Literal["bug", "security", "performance", "style", "maintainability", "other"]
Severity = Literal["low", "medium", "high", "critical"]
RiskLevel = Literal["low", "medium", "high"]


class Finding(BaseModel):
    issue_type: IssueType
    severity: Severity
    file: str = Field(description="Exact filename from the diff")
    line: int | None = Field(default=None, description="Line number in the new file, if known")
    explanation: str
    suggestion: str | None = None


class ReviewResult(BaseModel):
    summary: str = Field(description="1-3 sentence overview of the change and its risk")
    findings: list[Finding] = Field(default_factory=list)
    overall_risk: RiskLevel = "low"
