"""Billing Manager — generate invoices and manage billing for tenants.

Integrates with CostTracker to produce actionable billing data.
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

logger = logging.getLogger(__name__)


class Invoice(BaseModel):
    """A billing invoice."""

    id: str = Field(default_factory=lambda: f"inv_{uuid.uuid4().hex[:8]}")
    tenant_id: str = ""

    period_start: float = Field(default_factory=time.time)
    period_end: float = Field(default_factory=time.time)

    total_tokens: int = 0
    total_cost_usd: float = 0.0

    line_items: list[dict[str, Any]] = Field(default_factory=list)
    """List of line items: [{"description": "...", "amount": 0.0, "tokens": 1000}]"""

    discount_percent: float = 0.0
    tax_percent: float = 0.0

    @property
    def total_after_discount(self) -> float:
        return self.total_cost_usd * (1 - self.discount_percent / 100)

    @property
    def total_with_tax(self) -> float:
        after_discount = self.total_after_discount
        return after_discount * (1 + self.tax_percent / 100)

    @property
    def status(self) -> str:
        if self.total_cost_usd == 0:
            return "zero_balance"
        return "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": self.id,
            "tenant_id": self.tenant_id,
            "period": {
                "start": datetime.fromtimestamp(self.period_start, tz=UTC).isoformat(),
                "end": datetime.fromtimestamp(self.period_end, tz=UTC).isoformat(),
            },
            "subtotal": round(self.total_cost_usd, 6),
            "discount": f"{self.discount_percent}%",
            "tax": f"{self.tax_percent}%",
            "total_after_discount": round(self.total_after_discount, 6),
            "total_with_tax": round(self.total_with_tax, 6),
            "status": self.status,
            "line_items": self.line_items,
            "total_tokens": self.total_tokens,
        }


class BillingManager:
    """Generate and manage invoices for tenants.

    Usage:
        billing = BillingManager()

        invoice = billing.generate_invoice(
            tenant_id="tenant_123",
            period_start=time.time() - 86400 * 30,
            period_end=time.time(),
            usage_records=[...],
        )

        print(f"Invoice: ${invoice.total_with_tax:.4f}")
    """

    def __init__(
        self,
        storage_path: Path | str | None = None,
        default_discount: float = 0.0,
        default_tax: float = 0.0,
    ):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "billing")
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.default_discount = default_discount
        self.default_tax = default_tax
        self._invoices: list[Invoice] = []
        # Load previously persisted invoices so they survive restarts.
        self._load()

    def generate_invoice(
        self,
        tenant_id: str,
        period_start: float,
        period_end: float,
        usage_records: list[dict[str, Any]] | None = None,
        discount_percent: float = 0.0,
        tax_percent: float = 0.0,
    ) -> Invoice:
        """Generate an invoice from usage records.

        Args:
            tenant_id: The tenant's identifier
            period_start: Start of the billing period (unix timestamp)
            period_end: End of the billing period
            usage_records: List of usage records (must have cost_usd and model keys)
            discount_percent: Discount percentage
            tax_percent: Tax percentage

        Returns:
            Invoice with line items and totals
        """
        # Group by model for line items
        by_model: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"tokens": 0, "cost": 0.0, "calls": 0}
        )
        total_tokens = 0
        total_cost = 0.0

        if usage_records:
            for record in usage_records:
                model = record.get("model", "unknown")
                by_model[model]["tokens"] += record.get("total_tokens", 0)
                by_model[model]["cost"] += record.get("cost_usd", 0)
                by_model[model]["calls"] += 1
                total_tokens += record.get("total_tokens", 0)
                total_cost += record.get("cost_usd", 0)

        # Build line items
        line_items = []
        for model, data in sorted(by_model.items()):
            line_items.append(
                {
                    "description": f"{model} ({data['calls']} calls)",
                    "tokens": data["tokens"],
                    "amount": round(data["cost"], 6),
                }
            )

        # Create invoice
        invoice = Invoice(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            line_items=line_items,
            discount_percent=discount_percent or self.default_discount,
            tax_percent=tax_percent or self.default_tax,
        )

        self._invoices.append(invoice)
        self._save()

        logger.info(
            "Generated invoice %s for %s: $%.4f",
            invoice.id,
            tenant_id,
            invoice.total_with_tax,
        )

        return invoice

    def get_invoices(
        self,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> list[Invoice]:
        """Get invoices, optionally filtered by tenant."""
        invoices = self._invoices
        if tenant_id:
            invoices = [i for i in invoices if i.tenant_id == tenant_id]
        return invoices[-limit:]

    def get_total_billed(self, tenant_id: str | None = None) -> float:
        """Get total amount billed."""
        invoices = self._invoices
        if tenant_id:
            invoices = [i for i in invoices if i.tenant_id == tenant_id]
        return sum(i.total_with_tax for i in invoices)

    def export_invoice(self, invoice_id: str) -> str | None:
        """Export a specific invoice to JSON file."""
        invoice = next((i for i in self._invoices if i.id == invoice_id), None)
        if not invoice:
            return None

        path = self.storage_path / f"invoice_{invoice_id}.json"
        path.write_text(json.dumps(invoice.to_dict(), indent=2))
        return str(path)

    def _save(self) -> None:
        """Save invoices to disk."""
        try:
            path = self.storage_path / "invoices.json"
            data = [inv.to_dict() for inv in self._invoices[-100:]]
            path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.debug("Failed to save invoices: %s", e)

    def _load(self) -> None:
        """Load invoices from disk."""
        try:
            path = self.storage_path / "invoices.json"
            if path.exists():
                data = json.loads(path.read_text())
                for item in data:
                    self._invoices.append(Invoice(**item))
        except Exception as e:
            logger.debug("Failed to load invoices: %s", e)

    def __repr__(self) -> str:
        return f"BillingManager(invoices={len(self._invoices)})"
