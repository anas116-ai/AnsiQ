"""Advanced usage examples — full feature demonstration.

Shows how to combine agents, memory, skills, tools, and scheduling.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)


async def demo_memory_with_profile():
    """Demonstrate memory and profile management."""
    from ansiq.memory.episodic import EpisodicMemory
    from ansiq.memory.fts_store import FTSMemoryStore
    from ansiq.memory.profile import ProfileManager

    # Profile management
    profiles = ProfileManager()
    profile = profiles.get_profile("user_demo")
    profiles.add_trait("user_demo", "communication_style", "concise", 0.8)
    profiles.set_preference("user_demo", "temperature", 0.5)
    print(f"\nProfile created: {profile.user_id}")
    print(f"Trait: {profiles.get_trait('user_demo', 'communication_style')}")

    # Episodic memory
    store = FTSMemoryStore()
    episodes = EpisodicMemory(store=store, agent_id="demo_agent")

    ep_id = episodes.begin_episode("Research quantum computing advancements")
    episodes.record_step("Searched arXiv", "Found 10 relevant papers", success=True)
    episodes.record_step("Summarized findings", "Created 3-page summary", success=True)
    episodes.end_episode(summary="Completed quantum computing research")

    # Recall
    memories = episodes.recall("quantum computing")
    print(f"\nEpisodic recall: {len(memories)} episodes found")
    for mem in memories:
        print(f"  - {mem['summary']}")


async def demo_skills():
    """Demonstrate the skill system."""
    from ansiq.skills.base import BaseSkill, SkillResult
    from ansiq.skills.registry import SkillRegistry

    # Create a custom skill
    class DataAnalysisSkill(BaseSkill):
        name = "data_analysis"
        description = "Analyze structured data and extract insights"
        version = "1.0.0"
        category = "analytics"

        async def execute(self, data: str = "", analysis_type: str = "basic") -> SkillResult:
            # Simplified example
            lines = data.strip().split("\n")
            return SkillResult(
                success=True,
                output=f"Analysis complete: {len(lines)} data points analyzed",
                data={"rows": len(lines), "type": analysis_type},
            )

    # Register and use
    SkillRegistry.register_class(DataAnalysisSkill)
    skill = SkillRegistry.get("data_analysis")
    print(f"\nSkill registered: {skill}")
    print(f"Description: {skill.description}")

    result = await skill.execute(data="item1,10\nitem2,20\nitem3,30")
    print(f"Execution: {result.output}")


async def demo_scheduler():
    """Demonstrate the scheduler system."""
    from ansiq.scheduler.scheduler import Scheduler, next_run_time, parse_cron

    # Parse a cron expression
    parsed = parse_cron("0 9 * * 1-5")
    print(f"\nCron '0 9 * * 1-5' → minute={parsed[0]}, hour={parsed[1]}")

    # Calculate next run
    next_run = next_run_time("30 14 * * *")
    if next_run:
        print(f"Next run at: {next_run}")

    # Create a scheduler
    scheduler = Scheduler()

    async def my_task():
        print("Scheduled task executed!")

    scheduler.add_schedule(
        name="daily_report",
        cron_expression="0 9 * * *",
        handler=my_task,
        metadata={"task": "Generate daily report"},
    )

    print(f"Schedules: {len(scheduler.list_schedules())}")
    for s in scheduler.list_schedules():
        print(f"  - {s.name}: {s.cron_expression}")


async def demo_execution():
    """Demonstrate the execution system."""
    from ansiq.execution.executor import LocalExecutor

    executor = LocalExecutor()

    # Execute Python code
    result = await executor.execute("print('Hello from AnsiQ!')")
    print(f"\nPython execution: success={result.success}")
    print(f"Output: {result.output.strip()}")


async def main():
    print("=" * 60)
    print("AnsiQ Framework — Advanced Usage Examples")
    print("=" * 60)

    print("\n1. Memory & Profile Management")
    print("-" * 40)
    await demo_memory_with_profile()

    print("\n2. Skill System")
    print("-" * 40)
    await demo_skills()

    print("\n3. Scheduler")
    print("-" * 40)
    await demo_scheduler()

    print("\n4. Execution Environment")
    print("-" * 40)
    await demo_execution()

    print("\n" + "=" * 60)
    print("All advanced demos completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
