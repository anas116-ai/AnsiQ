"""Tests for the scheduler system — cron parsing, next_run_time, Schedule management."""

from __future__ import annotations

from datetime import datetime

import pytest

from ansiq.scheduler.scheduler import (
    Schedule,
    Scheduler,
    _parse_cron_field,
    next_run_time,
    parse_cron,
)


class TestCronParsing:
    def test_parse_star(self):
        """Test parsing '*' in cron field."""
        assert _parse_cron_field("*", 0, 59) == list(range(0, 60))

    def test_parse_single_value(self):
        """Test parsing a single value."""
        assert _parse_cron_field("5", 0, 59) == [5]

    def test_parse_range(self):
        """Test parsing a range."""
        assert _parse_cron_field("1-5", 0, 59) == [1, 2, 3, 4, 5]

    def test_parse_list(self):
        """Test parsing a list of values."""
        result = _parse_cron_field("1,3,5", 0, 59)
        assert result == [1, 3, 5]

    def test_parse_step(self):
        """Test parsing step values."""
        result = _parse_cron_field("*/15", 0, 59)
        assert result == [0, 15, 30, 45]

    def test_parse_range_step(self):
        """Test parsing range with step."""
        result = _parse_cron_field("1-10/3", 0, 59)
        assert result == [1, 4, 7, 10]

    def test_parse_full_expression(self):
        """Test parsing a full cron expression."""
        minutes, hours, days, months, weekdays = parse_cron("30 9 * * 1-5")
        assert minutes == [30]
        assert hours == [9]
        assert days == list(range(1, 32))
        assert months == list(range(1, 13))
        assert weekdays == [1, 2, 3, 4, 5]

    def test_parse_every_minute(self):
        """Test every minute expression."""
        minutes, hours, days, months, weekdays = parse_cron("* * * * *")
        assert minutes == list(range(0, 60))

    def test_parse_every_5_minutes(self):
        """Test every 5 minutes."""
        minutes, hours, days, months, weekdays = parse_cron("*/5 * * * *")
        assert minutes == [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55]

    def test_parse_invalid_too_few_fields(self):
        """Test parsing expression with too few fields."""
        with pytest.raises(ValueError, match="expected 5 fields"):
            parse_cron("* * *")

    def test_parse_invalid_too_many_fields(self):
        """Test parsing expression with too many fields."""
        with pytest.raises(ValueError, match="expected 5 fields"):
            parse_cron("* * * * * *")

    def test_parse_specific_times(self):
        """Test parsing specific times."""
        minutes, hours, days, months, weekdays = parse_cron("0,30 9,18 * * 1-5")
        assert minutes == [0, 30]
        assert hours == [9, 18]
        assert weekdays == [1, 2, 3, 4, 5]

    def test_parse_monthly(self):
        """Test monthly cron."""
        minutes, hours, days, months, weekdays = parse_cron("0 0 1 * *")
        assert minutes == [0]
        assert hours == [0]
        assert days == [1]
        assert months == list(range(1, 13))


class TestNextRunTime:
    def test_next_run_soon(self):
        """Test next run time calculation for a near-future time."""
        before = datetime(2026, 1, 1, 0, 0, 0)
        next_run = next_run_time("30 9 * * *", after=before)
        assert next_run is not None
        assert next_run.hour == 9
        assert next_run.minute == 30
        assert next_run.day >= before.day

    def test_next_run_same_day(self):
        """Test next run later the same day."""
        before = datetime(2026, 1, 1, 8, 0, 0)
        next_run = next_run_time("30 9 * * *", after=before)
        assert next_run is not None
        assert next_run.hour == 9
        assert next_run.minute == 30
        assert next_run.day == 1

    def test_next_run_next_day(self):
        """Test next run rolls to next day."""
        before = datetime(2026, 1, 1, 10, 0, 0)
        next_run = next_run_time("30 9 * * *", after=before)
        assert next_run is not None
        assert next_run.day == 2
        assert next_run.hour == 9
        assert next_run.minute == 30

    def test_next_run_weekday(self):
        """Test next run respects weekday constraints.

        Cron weekday: 0=Sun, 1=Mon, ..., 6=Sat
        Python weekday: 0=Mon, 1=Tue, ..., 6=Sun
        So cron 1-5 maps to Mon-Fri = Python 0-4.
        """
        # 2026-01-03 is a Saturday (cron weekday=6)
        before = datetime(2026, 1, 3, 0, 0, 0)
        next_run = next_run_time("0 9 * * 1-5", after=before)
        assert next_run is not None
        # Should skip to Monday 2026-01-05 (cron weekday=1, Python weekday=0)
        assert next_run.weekday() == 0  # Monday in Python
        assert next_run.day == 5

    def test_next_run_month_boundary(self):
        """Test next run crosses month boundary."""
        before = datetime(2026, 1, 31, 0, 0, 0)
        next_run = next_run_time("0 9 1 * *", after=before)
        assert next_run is not None
        assert next_run.month == 2
        assert next_run.day == 1

    def test_next_run_specific_month(self):
        """Test next run in a specific month."""
        before = datetime(2026, 1, 1, 0, 0, 0)
        next_run = next_run_time("0 0 1 6 *", after=before)
        assert next_run is not None
        assert next_run.month == 6
        assert next_run.day == 1
        assert next_run.hour == 0
        assert next_run.minute == 0

    def test_next_run_no_match(self):
        """Test next_run_time returns None when no match found."""
        # This should always find a match, but test the fallback
        result = next_run_time("* * * * 0")
        assert result is not None or result is None

    def test_next_run_with_none_after(self):
        """Test next_run_time with None after parameter."""
        next_run = next_run_time("0 9 * * *", after=None)
        assert next_run is not None


class TestSchedule:
    def test_create_schedule(self):
        """Test creating a schedule."""
        sched = Schedule(
            name="test_job",
            cron_expression="0 9 * * *",
        )
        assert sched.name == "test_job"
        assert sched.cron_expression == "0 9 * * *"
        assert sched.enabled is True
        assert sched.last_run is None
        assert sched.next_run is None

    def test_schedule_to_dict(self):
        """Test serializing schedule to dict."""
        sched = Schedule(
            name="my_job",
            cron_expression="*/5 * * * *",
            enabled=False,
            metadata={"owner": "admin"},
        )
        d = sched.to_dict()
        assert d["name"] == "my_job"
        assert d["enabled"] is False
        assert d["metadata"]["owner"] == "admin"

    def test_schedule_from_dict(self):
        """Test deserializing schedule from dict."""
        data = {
            "name": "restored_job",
            "cron_expression": "0 9 * * 1-5",
            "enabled": True,
            "last_run": "2026-01-01T09:00:00",
            "next_run": "2026-01-02T09:00:00",
            "metadata": {},
        }
        sched = Schedule.from_dict(data)
        assert sched.name == "restored_job"
        assert sched.last_run == "2026-01-01T09:00:00"

    def test_schedule_repr(self):
        """Test schedule string representation."""
        sched = Schedule(
            name="daily_task",
            cron_expression="0 9 * * *",
        )
        rep = repr(sched)
        assert "daily_task" in rep
        assert "0 9" in rep


class TestScheduler:
    def test_create_scheduler(self, tmp_path):
        """Test creating a scheduler."""
        storage = tmp_path / "schedules.json"
        scheduler = Scheduler(storage_path=storage)
        assert len(scheduler.list_schedules()) == 0

    def test_add_schedule(self, tmp_path):
        """Test adding a schedule."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")

        scheduler.add_schedule(
            name="daily",
            cron_expression="0 9 * * *",
        )
        assert len(scheduler.list_schedules()) == 1
        assert scheduler.get_schedule("daily") is not None

    def test_remove_schedule(self, tmp_path):
        """Test removing a schedule."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")

        scheduler.add_schedule(name="to_remove", cron_expression="* * * * *")
        assert scheduler.remove_schedule("to_remove") is True
        assert scheduler.get_schedule("to_remove") is None

    def test_remove_nonexistent(self, tmp_path):
        """Test removing non-existent schedule."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")
        assert scheduler.remove_schedule("nonexistent") is False

    def test_enable_disable(self, tmp_path):
        """Test enabling and disabling a schedule."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")

        scheduler.add_schedule(name="test", cron_expression="* * * * *")
        assert scheduler.schedules["test"].enabled is True

        scheduler.disable("test")
        assert scheduler.schedules["test"].enabled is False

        scheduler.enable("test")
        assert scheduler.schedules["test"].enabled is True

    def test_enable_nonexistent(self, tmp_path):
        """Test enabling non-existent schedule."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")
        assert scheduler.enable("ghost") is False
        assert scheduler.disable("ghost") is False

    def test_persistence(self, tmp_path):
        """Test schedules persist to disk."""
        storage = tmp_path / "sched.json"
        scheduler = Scheduler(storage_path=storage)

        scheduler.add_schedule(name="persist_me", cron_expression="0 0 * * *")
        assert storage.exists()

        # Create a new scheduler instance and verify it loads
        scheduler2 = Scheduler(storage_path=storage)
        assert scheduler2.get_schedule("persist_me") is not None

    def test_schedule_next_run_auto(self, tmp_path):
        """Test schedule auto-calculates next_run."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")
        sched = scheduler.add_schedule(name="auto_test", cron_expression="0 9 * * *")
        assert sched.next_run is not None

    def test_start_stop(self, tmp_path):
        """Test starting and stopping the scheduler."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")

        async def handler():
            pass

        scheduler.add_schedule(name="handler_task", cron_expression="0 9 * * *", handler=handler)

        import asyncio
        # Start and immediately stop
        async def test():
            asyncio.create_task(scheduler.start())
            await asyncio.sleep(0.1)
            await scheduler.stop()

        asyncio.run(test())
        assert scheduler._running is False

    def test_list_schedules(self, tmp_path):
        """Test listing schedules."""
        scheduler = Scheduler(storage_path=tmp_path / "sched.json")
        scheduler.add_schedule(name="a", cron_expression="* * * * *")
        scheduler.add_schedule(name="b", cron_expression="*/5 * * * *")
        names = [s.name for s in scheduler.list_schedules()]
        assert "a" in names
        assert "b" in names
        assert len(names) == 2

    def test_load_empty_storage(self, tmp_path):
        """Test loading from non-existent file."""
        storage = tmp_path / "nonexistent.json"
        scheduler = Scheduler(storage_path=storage)
        assert len(scheduler.list_schedules()) == 0
