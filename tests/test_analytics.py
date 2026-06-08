"""Tests for the analytics module — CostTracker, BillingManager."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ansiq.analytics.cost_tracker import CostSummary, CostTracker, UsageRecord


class TestUsageRecord:
    """Test UsageRecord model."""

    def test_create_record(self):
        rec = UsageRecord(
            agent_name="test_agent",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0025,
        )
        assert rec.agent_name == "test_agent"
        assert rec.model == "gpt-4o"
        assert rec.total_tokens == 150
        assert rec.cost_usd == 0.0025
        assert rec.success is True

    def test_datetime_iso(self):
        rec = UsageRecord()
        iso = rec.datetime_iso
        assert "T" in iso
        assert iso.endswith("+00:00") or "+" in iso

    def test_cost_display(self):
        rec = UsageRecord(cost_usd=0.0123)
        assert "$0.0123" in rec.cost_display

        rec2 = UsageRecord(cost_usd=0.000001)
        assert "$0.000001" in rec2.cost_display

        rec3 = UsageRecord(cost_usd=0.0)
        assert "$0.0000" in rec3.cost_display

    def test_default_id(self):
        rec = UsageRecord()
        assert rec.id.startswith("usage_")


class TestCostSummary:
    """Test CostSummary model."""

    def test_empty_summary(self):
        s = CostSummary()
        assert s.total_tokens == 0
        assert s.total_cost_usd == 0.0
        assert s.total_calls == 0

    def test_with_data(self):
        s = CostSummary(
            total_tokens=1000,
            total_cost_usd=0.05,
            total_calls=5,
            avg_cost_per_call=0.01,
            avg_tokens_per_call=200.0,
        )
        assert s.total_tokens == 1000
        assert s.total_calls == 5


class TestCostTracker:
    """Test CostTracker recording and summaries."""

    def test_create_tracker(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        assert tracker is not None
        assert tracker.storage_path == tmp_path

    def test_record_usage(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        rec = tracker.record(
            agent_name="test_agent",
            model="gpt-4o",
            prompt_tokens=500,
            completion_tokens=500,
        )
        assert rec is not None
        assert rec.total_tokens == 1000
        assert rec.cost_usd > 0
        assert rec.success is True

    def test_record_with_provider(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        rec = tracker.record(
            agent_name="agent1",
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert rec.provider == "anthropic"

    def test_record_with_role_and_task(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        rec = tracker.record(
            agent_name="writer",
            agent_role="Writer",
            task_description="Write a blog post",
            model="gpt-4o-mini",
            prompt_tokens=50,
            completion_tokens=30,
        )
        assert rec.agent_role == "Writer"
        assert "blog post" in rec.task_description

    def test_get_summary_all(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="a1", model="gpt-4o", prompt_tokens=100, completion_tokens=100)
        tracker.record(agent_name="a2", model="gpt-4o-mini", prompt_tokens=200, completion_tokens=100)

        summary = tracker.get_summary()
        assert summary.total_calls == 2
        assert summary.total_tokens >= 500
        assert summary.total_cost_usd > 0

    def test_get_summary_since(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="old", model="gpt-4o", prompt_tokens=10, completion_tokens=10)

        future = time.time() + 86400 * 365
        summary = tracker.get_summary(since=future)
        assert summary.total_calls == 0

    def test_get_summary_by_agent(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="agent_a", model="gpt-4o", prompt_tokens=100, completion_tokens=100)
        tracker.record(agent_name="agent_b", model="gpt-4o", prompt_tokens=50, completion_tokens=50)

        summary = tracker.get_summary(agent="agent_a")
        assert summary.total_calls == 1

    def test_get_summary_by_model(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="a1", model="gpt-4o", prompt_tokens=100, completion_tokens=100)
        tracker.record(agent_name="a2", model="gpt-4o-mini", prompt_tokens=50, completion_tokens=50)

        summary = tracker.get_summary(model="gpt-4o")
        assert summary.total_calls == 1

    def test_get_records_with_limit(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        for i in range(5):
            tracker.record(agent_name=f"agent_{i}", model="gpt-4o",
                           prompt_tokens=10, completion_tokens=10)

        records = tracker.get_records(limit=3)
        assert len(records) == 3

    def test_get_records_limit_zero(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="a1", model="gpt-4o", prompt_tokens=10, completion_tokens=10)
        records = tracker.get_records(limit=0)
        assert records == []

    def test_get_records_with_offset(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        for i in range(5):
            tracker.record(agent_name=f"agent_{i}", model="gpt-4o",
                           prompt_tokens=10, completion_tokens=10)

        records = tracker.get_records(limit=100, offset=3)
        assert len(records) == 2

    def test_get_agent_reports(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="alpha", model="gpt-4o", prompt_tokens=100, completion_tokens=100)
        tracker.record(agent_name="beta", model="gpt-4o-mini", prompt_tokens=50, completion_tokens=50)

        reports = tracker.get_agent_reports()
        assert len(reports) == 2
        assert any(r["agent"] == "alpha" for r in reports)

    def test_get_total_cost(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="a1", model="gpt-4o", prompt_tokens=100, completion_tokens=100)
        total = tracker.get_total_cost()
        assert total > 0

    def test_check_budget_within_limit(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path, budget_limit_usd=100.0)
        within, current, limit = tracker.check_budget()
        assert within is True
        assert current < 100.0

    def test_check_budget_no_limit(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        within, current, limit = tracker.check_budget()
        assert within is True
        assert limit == 0.0

    def test_export_json(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="export_test", model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        export_path = tracker.export_json(path=tmp_path / "costs.json")
        assert Path(export_path).exists()
        data = json.loads(Path(export_path).read_text())
        assert data["total_records"] == 1

    def test_export_csv(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="csv_test", model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        export_path = tracker.export_csv(path=tmp_path / "costs.csv")
        assert Path(export_path).exists()
        content = Path(export_path).read_text()
        assert "timestamp,agent" in content

    def test_reset(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="a1", model="gpt-4o", prompt_tokens=10, completion_tokens=10)
        assert tracker.get_total_cost() > 0
        tracker.reset()
        assert tracker.get_total_cost() == 0.0

    def test_persistence(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="persistent", model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        tracker2 = CostTracker(storage_path=tmp_path)
        assert tracker2.get_total_cost() > 0

    def test_repr(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        rep = repr(tracker)
        assert "CostTracker" in rep

    def test_local_model_pricing(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        rec = tracker.record(agent_name="local_test", model="llama-3.2-3b",
                             prompt_tokens=1000, completion_tokens=1000)
        assert rec.cost_usd == 0.0

    def test_provider_detection(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        rec = tracker.record(agent_name="detect_test", model="gpt-4o",
                             prompt_tokens=10, completion_tokens=10)
        assert rec.provider == "openai"

    def test_breakdowns(self, tmp_path):
        tracker = CostTracker(storage_path=tmp_path)
        tracker.record(agent_name="a1", model="gpt-4o", prompt_tokens=100, completion_tokens=100)
        tracker.record(agent_name="a2", model="gpt-4o-mini", prompt_tokens=200, completion_tokens=100)
        summary = tracker.get_summary()
        assert len(summary.by_provider) >= 1
        assert len(summary.by_model) >= 1
        assert len(summary.by_agent) >= 1


class TestBillingManager:
    """Test BillingManager invoice generation."""

    def test_import_billing(self):
        from ansiq.analytics.billing import BillingManager
        assert BillingManager is not None

    def test_generate_invoice(self, tmp_path):
        from ansiq.analytics.billing import BillingManager

        billing = BillingManager(storage_path=tmp_path)
        inv = billing.generate_invoice(
            tenant_id="tenant_1",
            period_start=time.time() - 86400 * 30,
            period_end=time.time(),
            usage_records=[
                {"model": "gpt-4o", "total_tokens": 1000, "cost_usd": 0.05},
                {"model": "gpt-4o-mini", "total_tokens": 500, "cost_usd": 0.01},
            ],
        )
        assert inv.id.startswith("inv_")
        assert inv.tenant_id == "tenant_1"
        assert inv.total_tokens == 1500
        assert round(inv.total_cost_usd, 4) == 0.06
        assert len(inv.line_items) == 2

    def test_invoice_with_discount_and_tax(self, tmp_path):
        from ansiq.analytics.billing import BillingManager

        billing = BillingManager(storage_path=tmp_path)
        inv = billing.generate_invoice(
            tenant_id="tenant_2",
            period_start=time.time() - 86400 * 30,
            period_end=time.time(),
            usage_records=[{"model": "gpt-4o", "total_tokens": 1000, "cost_usd": 1.00}],
            discount_percent=10.0,
            tax_percent=8.0,
        )
        assert inv.total_cost_usd == 1.0
        assert inv.total_after_discount == 0.9
        assert round(inv.total_with_tax, 4) == 0.972

    def test_invoice_no_records(self, tmp_path):
        from ansiq.analytics.billing import BillingManager
        billing = BillingManager(storage_path=tmp_path)
        inv = billing.generate_invoice(
            tenant_id="tenant_empty", period_start=time.time(), period_end=time.time())
        assert inv.total_tokens == 0
        assert inv.total_cost_usd == 0.0
        assert inv.status == "zero_balance"

    def test_get_invoices(self, tmp_path):
        from ansiq.analytics.billing import BillingManager
        billing = BillingManager(storage_path=tmp_path)
        billing.generate_invoice(tenant_id="t1", period_start=0, period_end=1)
        billing.generate_invoice(tenant_id="t2", period_start=0, period_end=1)
        assert len(billing.get_invoices()) == 2
        assert len(billing.get_invoices(tenant_id="t1")) == 1

    def test_get_total_billed(self, tmp_path):
        from ansiq.analytics.billing import BillingManager
        billing = BillingManager(storage_path=tmp_path)
        billing.generate_invoice(tenant_id="t1", period_start=0, period_end=1,
                                 usage_records=[{"model": "gpt-4o", "total_tokens": 100, "cost_usd": 0.50}])
        assert billing.get_total_billed(tenant_id="t1") > 0

    def test_invoice_to_dict(self, tmp_path):
        from ansiq.analytics.billing import BillingManager
        billing = BillingManager(storage_path=tmp_path)
        inv = billing.generate_invoice(tenant_id="t1", period_start=0, period_end=1,
                                       usage_records=[{"model": "gpt-4o", "total_tokens": 100, "cost_usd": 0.50}])
        d = inv.to_dict()
        assert "invoice_id" in d

    def test_export_invoice(self, tmp_path):
        from ansiq.analytics.billing import BillingManager
        billing = BillingManager(storage_path=tmp_path)
        inv = billing.generate_invoice(tenant_id="t1", period_start=0, period_end=1,
                                       usage_records=[{"model": "gpt-4o", "total_tokens": 100, "cost_usd": 0.50}])
        export_path = billing.export_invoice(inv.id)
        assert export_path is not None
        assert Path(export_path).exists()

    def test_persistence(self, tmp_path):
        from ansiq.analytics.billing import BillingManager
        billing = BillingManager(storage_path=tmp_path)
        billing.generate_invoice(tenant_id="persist", period_start=0, period_end=1,
                                 usage_records=[{"model": "gpt-4o", "total_tokens": 100, "cost_usd": 0.50}])
        billing2 = BillingManager(storage_path=tmp_path)
        assert len(billing2.get_invoices()) == 1

    def test_repr(self, tmp_path):
        from ansiq.analytics.billing import BillingManager
        billing = BillingManager(storage_path=tmp_path)
        rep = repr(billing)
        assert "BillingManager" in rep
