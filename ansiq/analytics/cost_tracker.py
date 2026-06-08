"""Cost Tracker — track token usage and costs per agent, task, and run.

Integrates with AnsiQ's hook system to automatically record costs.
Provides detailed breakdowns for cost analytics and optimization.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ansiq.llm.router import ModelRouter

logger = logging.getLogger(__name__)


class UsageRecord(BaseModel):
    """A single usage record — one LLM call."""

    id: str = Field(default_factory=lambda: f"usage_{uuid.uuid4().hex[:8]}")
    timestamp: float = Field(default_factory=time.time)

    agent_name: str = ""
    agent_role: str = ""
    task_description: str = ""

    provider: str = ""
    model: str = ""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    cost_usd: float = 0.0
    estimated_cost_usd: float = 0.0

    duration_ms: float = 0.0
    success: bool = True

    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def datetime_iso(self) -> str:
        """Get human-readable timestamp."""
        return datetime.fromtimestamp(self.timestamp, tz=UTC).isoformat()

    @property
    def cost_display(self) -> str:
        """Get cost in readable format."""
        if self.cost_usd >= 0.01:
            return f"${self.cost_usd:.4f}"
        elif self.cost_usd > 0:
            return f"${self.cost_usd:.6f}"
        return "$0.0000"


class CostSummary(BaseModel):
    """Summary of costs for a period/agent/project."""

    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_calls: int = 0

    by_provider: dict[str, float] = Field(default_factory=dict)
    by_model: dict[str, float] = Field(default_factory=dict)
    by_agent: dict[str, float] = Field(default_factory=dict)

    avg_cost_per_call: float = 0.0
    avg_tokens_per_call: float = 0.0
    total_duration_ms: float = 0.0

    period_start: float | None = None
    period_end: float | None = None


class CostTracker:
    """Tracks token usage and costs for all LLM calls.

    Features:
    - Automatic recording via AnsiQ hooks
    - Per-agent, per-model, per-task breakdowns
    - Budget limits and alerts
    - Export to JSON/CSV
    - Integration with ModelRouter for pricing

    Usage:
        tracker = CostTracker()

        # Record usage
        tracker.record(
            agent_name="Researcher",
            model="gpt-4o",
            prompt_tokens=500,
            completion_tokens=200,
        )

        # Get summary
        summary = tracker.get_summary()
        print(f"Total cost: ${summary.total_cost_usd:.4f}")

        # Export
        tracker.export_json("cost_report.json")
    """

    # Model pricing (USD per 1K tokens)
    DEFAULT_PRICING: dict[str, dict[str, float]] = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "gpt-4-turbo": {"input": 0.01, "output": 0.03},
        "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
        "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
        "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
        "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
        "llama-3.2-3b": {"input": 0.0, "output": 0.0},  # Local
        "llama-3.2-8b": {"input": 0.0, "output": 0.0},  # Local
        "llama-3.2-70b": {"input": 0.00059, "output": 0.00079},
        "mixtral-8x7b": {"input": 0.0003, "output": 0.0003},
    }

    def __init__(
        self,
        storage_path: Path | str | None = None,
        budget_limit_usd: float = 0.0,
        router: ModelRouter | None = None,
    ):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "costs")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.budget_limit_usd = budget_limit_usd
        self.router = router
        self._records: list[UsageRecord] = []
        self._load()

    def record(
        self,
        agent_name: str = "",
        agent_role: str = "",
        task_description: str = "",
        provider: str = "",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: float = 0.0,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> UsageRecord:
        """Record an LLM usage event.

        Calculates cost automatically based on model pricing.

        Returns:
            The created UsageRecord
        """
        # Calculate cost
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens, provider)

        record = UsageRecord(
            agent_name=agent_name,
            agent_role=agent_role,
            task_description=task_description[:100],
            provider=provider or self._get_provider_for_model(model),
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost,
            estimated_cost_usd=cost,
            duration_ms=duration_ms,
            success=success,
            metadata=metadata or {},
        )

        self._records.append(record)

        # Check budget
        if self.budget_limit_usd > 0:
            total = self.get_total_cost()
            if total > self.budget_limit_usd:
                logger.warning(
                    "Budget limit exceeded! $%.4f / $%.4f",
                    total,
                    self.budget_limit_usd,
                )

        self._save()
        return record

    def _calculate_cost(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        provider: str = "",
    ) -> float:
        """Calculate cost for an LLM call based on model pricing."""
        # Check if router has pricing info
        if self.router:
            for profile in self.router._profiles:
                if profile.model_name == model:
                    input_cost = (prompt_tokens / 1000) * profile.cost_per_1k_input
                    output_cost = (completion_tokens / 1000) * profile.cost_per_1k_output
                    return input_cost + output_cost

        # Use default pricing
        pricing = self.DEFAULT_PRICING.get(model, {"input": 0.0, "output": 0.0})
        input_cost = (prompt_tokens / 1000) * pricing["input"]
        output_cost = (completion_tokens / 1000) * pricing["output"]
        return input_cost + output_cost

    def _get_provider_for_model(self, model: str) -> str:
        """Guess provider from model name."""
        model_lower = model.lower()
        if "gpt" in model_lower:
            return "openai"
        elif "claude" in model_lower:
            return "anthropic"
        elif "llama" in model_lower or "mistral" in model_lower or "mixtral" in model_lower:
            return "ollama"
        elif "command" in model_lower:
            return "cohere"
        return "unknown"

    def get_summary(
        self,
        since: float | None = None,
        agent: str | None = None,
        model: str | None = None,
    ) -> CostSummary:
        """Get cost summary for the specified period/filter."""
        records = self._records

        # Apply filters
        if since:
            records = [r for r in records if r.timestamp >= since]
        if agent:
            records = [r for r in records if r.agent_name == agent]
        if model:
            records = [r for r in records if r.model == model]

        if not records:
            return CostSummary()

        # Calculate totals
        total_tokens = sum(r.total_tokens for r in records)
        total_cost = sum(r.cost_usd for r in records)
        total_calls = len(records)
        total_duration = sum(r.duration_ms for r in records)

        # Breakdowns
        by_provider: dict[str, float] = defaultdict(float)
        by_model: dict[str, float] = defaultdict(float)
        by_agent: dict[str, float] = defaultdict(float)

        for r in records:
            by_provider[r.provider] += r.cost_usd
            by_model[r.model] += r.cost_usd
            by_agent[r.agent_name] += r.cost_usd

        return CostSummary(
            total_tokens=total_tokens,
            total_cost_usd=round(total_cost, 6),
            total_calls=total_calls,
            by_provider=dict(by_provider),
            by_model=dict(by_model),
            by_agent=dict(by_agent),
            avg_cost_per_call=round(total_cost / max(total_calls, 1), 6),
            avg_tokens_per_call=round(total_tokens / max(total_calls, 1), 1),
            total_duration_ms=total_duration,
            period_start=records[0].timestamp if records else None,
            period_end=records[-1].timestamp if records else None,
        )

    def get_total_cost(self) -> float:
        """Get total cost across all records."""
        return sum(r.cost_usd for r in self._records)

    def get_records(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UsageRecord]:
        """Get recent usage records with optional offset (from the end)."""
        if limit <= 0:
            return []
        if offset < 0:
            offset = 0
        # Slice from the end: skip `offset` most-recent, return next `limit`.
        end_index = len(self._records) - offset
        start_index = max(0, end_index - limit)
        return self._records[start_index:end_index]

    def get_agent_reports(self) -> list[dict[str, Any]]:
        """Get per-agent cost reports."""
        agent_records: dict[str, list[UsageRecord]] = defaultdict(list)
        for r in self._records:
            agent_records[r.agent_name].append(r)

        reports = []
        for agent, records in agent_records.items():
            total_cost = sum(r.cost_usd for r in records)
            total_tokens = sum(r.total_tokens for r in records)
            total_calls = len(records)
            reports.append(
                {
                    "agent": agent or "unknown",
                    "total_cost": round(total_cost, 6),
                    "total_tokens": total_tokens,
                    "total_calls": total_calls,
                    "avg_cost_per_call": round(total_cost / max(total_calls, 1), 6),
                    "models_used": list(set(r.model for r in records)),
                }
            )

        return sorted(reports, key=lambda x: x["total_cost"], reverse=True)

    def check_budget(self) -> tuple[bool, float, float]:
        """Check if current usage is within budget.

        Returns:
            (within_budget, current_spend, budget_limit)
        """
        total = self.get_total_cost()
        if self.budget_limit_usd > 0:
            return (total <= self.budget_limit_usd, total, self.budget_limit_usd)
        return (True, total, 0.0)

    def export_json(self, path: Path | str | None = None) -> str:
        """Export usage records to JSON file."""
        path = Path(path or self.storage_path / "usage_report.json")

        data = {
            "export_time": time.time(),
            "total_records": len(self._records),
            "total_cost": round(self.get_total_cost(), 6),
            "records": [
                {
                    "timestamp": r.datetime_iso,
                    "agent": r.agent_name,
                    "model": r.model,
                    "tokens": r.total_tokens,
                    "cost": r.cost_usd,
                    "success": r.success,
                }
                for r in self._records[-500:]  # Last 500 records
            ],
        }

        path.write_text(json.dumps(data, indent=2))
        logger.info("Exported %d records to %s", len(data["records"]), path)
        return str(path)

    def export_csv(self, path: Path | str | None = None) -> str:
        """Export usage records to CSV file."""
        path = Path(path or self.storage_path / "usage_report.csv")

        lines = [
            "timestamp,agent,provider,model,"
            "prompt_tokens,completion_tokens,total_tokens,"
            "cost_usd,duration_ms,success"
        ]

        for r in self._records:
            lines.append(
                f"{r.datetime_iso},{r.agent_name},{r.provider},{r.model},"
                f"{r.prompt_tokens},{r.completion_tokens},{r.total_tokens},"
                f"{r.cost_usd:.6f},{r.duration_ms:.1f},{r.success}"
            )

        path.write_text("\n".join(lines))
        logger.info("Exported %d records to %s", len(self._records), path)
        return str(path)

    def _save(self) -> None:
        """Save records to disk (keeps last 1000 in memory file)."""
        try:
            path = self.storage_path / "recent.json"
            recent = self._records[-200:]
            data = [
                {
                    "agent_name": r.agent_name,
                    "model": r.model,
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "cost_usd": r.cost_usd,
                    "timestamp": r.timestamp,
                    "success": r.success,
                }
                for r in recent
            ]
            path.write_text(json.dumps(data))
        except Exception as e:
            logger.debug("Failed to save cost records: %s", e)

    def _load(self) -> None:
        """Load recent records from disk."""
        try:
            path = self.storage_path / "recent.json"
            if path.exists():
                data = json.loads(path.read_text())
                for item in data[-500:]:
                    self._records.append(UsageRecord(**item))
        except Exception as e:
            logger.debug("Failed to load cost records: %s", e)

    def reset(self) -> None:
        """Reset all cost tracking data."""
        self._records.clear()
        try:
            path = self.storage_path / "recent.json"
            if path.exists():
                path.unlink()
        except Exception:
            logger.warning("Cost tracker reset failed for %s", path)
        logger.info("Cost tracker reset")

    def __repr__(self) -> str:
        return f"CostTracker(records={len(self._records)}, total=${self.get_total_cost():.4f})"
