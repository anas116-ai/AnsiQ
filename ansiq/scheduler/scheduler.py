"""Scheduler — cron-based task automation for agents.

Allows agents to run tasks on schedules (cron expressions)
with persistence and error handling.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEDULER_DB_PATH = Path.home() / ".ansiq" / "schedules.json"


class Schedule:
    """A scheduled task with cron expression and handler.

    Attributes:
        name: Unique name for this schedule.
        cron_expression: Standard cron expression (minute hour day month weekday).
        enabled: Whether the schedule is active.
        last_run: ISO timestamp of last execution.
        next_run: ISO timestamp of next scheduled execution.
        metadata: Arbitrary metadata for the schedule.
    """

    def __init__(
        self,
        name: str,
        cron_expression: str,
        handler: Callable | None = None,
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ):
        self.name = name
        self.cron_expression = cron_expression
        self.handler = handler
        self.enabled = enabled
        self.last_run: str | None = None
        self.next_run: str | None = None
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cron_expression": self.cron_expression,
            "enabled": self.enabled,
            "last_run": self.last_run.isoformat()
            if isinstance(self.last_run, datetime)
            else self.last_run,
            "next_run": self.next_run.isoformat()
            if isinstance(self.next_run, datetime)
            else self.next_run,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schedule:
        s = cls(
            name=data["name"],
            cron_expression=data["cron_expression"],
            enabled=data.get("enabled", True),
            metadata=data.get("metadata", {}),
        )
        s.last_run = data.get("last_run")
        s.next_run = data.get("next_run")
        return s

    def __repr__(self) -> str:
        return (
            f"Schedule(name='{self.name}', cron='{self.cron_expression}', enabled={self.enabled})"
        )


def parse_cron(expression: str) -> tuple[list[int], list[int], list[int], list[int], list[int]]:
    """Parse a cron expression into its components.

    Supports standard 5-field cron: minute hour day month weekday.
    Returns tuple of (minutes, hours, days, months, weekdays) as lists.
    """
    fields = expression.strip().split()
    if len(fields) != 5:
        raise ValueError(
            f"Invalid cron expression '{expression}': expected 5 fields, got {len(fields)}"
        )

    parsers = [
        ("minute", 0, 59),
        ("hour", 0, 23),
        ("day", 1, 31),
        ("month", 1, 12),
        ("weekday", 0, 6),
    ]

    result = []
    for (name, low, high), field in zip(parsers, fields, strict=False):
        values = _parse_cron_field(field, low, high)
        if not values:
            raise ValueError(f"Invalid {name} value in cron expression '{expression}'")
        result.append(values)

    return tuple(result)  # type: ignore


def _parse_cron_field(field: str, low: int, high: int) -> list[int]:
    """Parse a single cron field (supports *, ranges, and step values)."""
    field = field.strip()

    if field == "*":
        return list(range(low, high + 1))

    # Handle step: */5, 1-10/2
    if "/" in field:
        base, step = field.split("/", 1)
        step = int(step)
        if base == "*":
            return list(range(low, high + 1, step))
        start, end = base.split("-", 1)
        return list(range(int(start), int(end) + 1, step))

    # Handle range: 1-5
    if "-" in field:
        start, end = field.split("-", 1)
        return list(range(int(start), int(end) + 1))

    # Handle list: 1,2,3
    if "," in field:
        return [int(x.strip()) for x in field.split(",")]

    # Single value
    return [int(field)]


def next_run_time(cron_expression: str, after: datetime | None = None) -> datetime | None:
    """Calculate the next datetime matching the cron expression."""
    after = after or datetime.now()

    minutes, hours, days, months, weekdays = parse_cron(cron_expression)
    year = after.year
    month = after.month

    # Try to find a matching time within the next 12 months
    for _ in range(12):
        if month not in months:
            month += 1
            if month > 12:
                month = 1
                year += 1
            continue

        max_day = calendar.monthrange(year, month)[1]
        for day in (d for d in days if d <= max_day):
            if day < after.day and month == after.month and year == after.year:
                continue

            # Check weekday (convert Python weekday 0=Mon..6=Sun to cron 0=Sun..6=Sat)
            weekday = date(year, month, day).weekday()
            cron_weekday = (weekday + 1) % 7  # Cron: 0=Sun, 1=Mon, ..., 6=Sat
            if cron_weekday not in weekdays:
                continue

            for hour in hours:
                for minute in minutes:
                    candidate = datetime(year, month, day, hour, minute, 0)
                    if after is None or candidate > after:
                        return candidate

            # No matching time this day, continue to next day

        # If we didn't find a match in this month, try next
        month += 1
        if month > 12:
            month = 1
            year += 1

    return None


class Scheduler:
    """Cron-based task scheduler.

    Manages schedules, persists them to disk, and executes
    handlers on schedule.
    """

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or _SCHEDULER_DB_PATH
        self.schedules: dict[str, Schedule] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._load_schedules()

    def add_schedule(
        self,
        name: str,
        cron_expression: str,
        handler: Callable | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Schedule:
        """Register a new schedule."""
        schedule = Schedule(
            name=name,
            cron_expression=cron_expression,
            handler=handler,
            metadata=metadata,
        )
        schedule.next_run = next_run_time(cron_expression)
        self.schedules[name] = schedule
        self._save_schedules()
        logger.info("Added schedule: %s (%s)", name, cron_expression)
        return schedule

    def remove_schedule(self, name: str) -> bool:
        """Remove a schedule by name."""
        if name in self.schedules:
            del self.schedules[name]
            if name in self._tasks:
                self._tasks[name].cancel()
                del self._tasks[name]
            self._save_schedules()
            logger.info("Removed schedule: %s", name)
            return True
        return False

    def get_schedule(self, name: str) -> Schedule | None:
        """Get a schedule by name."""
        return self.schedules.get(name)

    def list_schedules(self) -> list[Schedule]:
        """List all registered schedules."""
        return list(self.schedules.values())

    def enable(self, name: str) -> bool:
        """Enable a schedule."""
        if name in self.schedules:
            self.schedules[name].enabled = True
            self._save_schedules()
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a schedule."""
        if name in self.schedules:
            self.schedules[name].enabled = False
            self._save_schedules()
            return True
        return False

    async def start(self) -> None:
        """Start the scheduler loop."""
        self._running = True
        logger.info("Scheduler started with %d schedules", len(self.schedules))

        while self._running:
            now = datetime.now()
            for name, schedule in self.schedules.items():
                if not schedule.enabled or not schedule.handler:
                    continue

                if schedule.next_run and now >= datetime.fromisoformat(schedule.next_run):
                    logger.info("Triggering scheduled task: %s", name)
                    schedule.last_run = now.isoformat()
                    schedule.next_run = next_run_time(schedule.cron_expression, after=now)
                    schedule.next_run = schedule.next_run.isoformat() if schedule.next_run else None

                    if name not in self._tasks or self._tasks[name].done():
                        self._tasks[name] = asyncio.create_task(
                            self._execute_handler(name, schedule)
                        )

            self._save_schedules()
            await asyncio.sleep(30)  # Check every 30 seconds

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        for _name, task in self._tasks.items():
            task.cancel()
        self._tasks.clear()
        logger.info("Scheduler stopped")

    async def _execute_handler(self, name: str, schedule: Schedule) -> None:
        """Execute a schedule's handler."""
        try:
            if asyncio.iscoroutinefunction(schedule.handler):
                await schedule.handler()
            else:
                await asyncio.to_thread(schedule.handler)
            logger.debug("Schedule '%s' executed successfully", name)
        except Exception as e:
            logger.error("Schedule '%s' failed: %s", name, e)

    def _load_schedules(self) -> None:
        """Load schedules from disk."""
        if not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text())
            self.schedules = {name: Schedule.from_dict(sched) for name, sched in data.items()}
            logger.debug("Loaded %d schedules", len(self.schedules))
        except Exception as e:
            logger.warning("Failed to load schedules: %s", e)

    def _save_schedules(self) -> None:
        """Save schedules to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {name: s.to_dict() for name, s in self.schedules.items()}
            self.storage_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.warning("Failed to save schedules: %s", e)
