"""AnsiQ Next-Gen Features — Complete Demo

This example demonstrates ALL 5 new features:
1. DAG Orchestrator — Parallel task execution
2. Swarm Intelligence — Agent voting & debating
3. Multi-Model Router — Smart model selection
4. Auto-Tool Discovery — @ansiq_tool decorator
5. Parallel Executor — Batch processing

Run: python -m examples.nextgen_features
"""

import asyncio
import logging
import sys

# Force UTF-8 stdout on Windows so box-drawing characters (e.g. '\u2588')
# used as visual separators don't crash with UnicodeEncodeError under the
# default cp1252 console encoding.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

logger = logging.getLogger(__name__)


async def demo_dag_orchestrator():
    """Demo 1: DAG-based parallel task execution."""
    print("\n" + "=" * 60)
    print("🚀 DAG ORCHESTRATOR")
    print("=" * 60)

    from ansiq.orchestration.dag import DAG, DAGNode

    # Create a research pipeline DAG
    dag = DAG("research_pipeline", "Research and analyze a topic")

    # Add nodes with dependencies
    dag.add_node(DAGNode(
        id="search",
        name="Search",
        description="Search for initial information",
    ))

    dag.add_node(DAGNode(
        id="analyze",
        name="Analyze",
        description="Analyze search results",
        depends_on=["search"],
    ))

    dag.add_node(DAGNode(
        id="verify",
        name="Verify",
        description="Verify findings from alternative sources",
        depends_on=["search"],
    ))

    dag.add_node(DAGNode(
        id="synthesize",
        name="Synthesize",
        description="Synthesize analysis and verification",
        depends_on=["analyze", "verify"],
    ))

    dag.add_node(DAGNode(
        id="report",
        name="Write Report",
        description="Write final report",
        depends_on=["synthesize"],
    ))

    print(f"Created DAG: {dag}")
    print(f"Visualization:\n{dag.visualize()}\n")

    # Show topological order
    print("Topological sort:", [n.name for n in dag._topological_sort()])

    # Show that test execution happens without LLM
    print("\n✅ DAG Orchestrator ready for execution!")
    print("   (Run with actual agents to execute tasks)")

    # Validate the DAG (should pass)
    try:
        dag._validate()
        print("   ✓ DAG validation passed (no cycles, all deps valid)")
    except ValueError as e:
        print(f"   ✗ DAG validation failed: {e}")


async def demo_swarm_intelligence():
    """Demo 2: Swarm Intelligence without actual LLM calls."""
    print("\n" + "=" * 60)
    print("🐝 SWARM INTELLIGENCE")
    print("=" * 60)

    from ansiq.swarm.consensus import ConsensusEngine, ConsensusMethod
    from ansiq.swarm.intelligence import (
        AgentOpinion,
        ConsensusResult,
        VoteType,
    )

    # 1. Show ConsensusEngine works standalone
    print("\n1️⃣ Consensus Engine (standalone)")

    engine = ConsensusEngine(method=ConsensusMethod.WEIGHTED)

    opinions = [
        AgentOpinion(
            agent_name="Researcher",
            agent_role="Researcher",
            vote=VoteType.AGREE,
            reasoning="The data supports this conclusion",
            confidence=0.85,
        ),
        AgentOpinion(
            agent_name="Analyst",
            agent_role="Data Analyst",
            vote=VoteType.STRONGLY_AGREE,
            reasoning="Multiple studies confirm this finding",
            confidence=0.92,
        ),
        AgentOpinion(
            agent_name="Critic",
            agent_role="Devil's Advocate",
            vote=VoteType.DISAGREE,
            reasoning="The sample size is too small",
            confidence=0.65,
        ),
    ]

    winner, confidence, metadata = engine.resolve(opinions)
    print(f"   Winner vote: {winner.value}")
    print(f"   Confidence: {confidence:.2%}")
    print(f"   Method: {metadata.get('method', 'unknown')}")

    # 2. Show consensus algorithms
    print("\n2️⃣ Consensus Methods Comparison")

    for method in ConsensusMethod:
        eng = ConsensusEngine(method=method)
        w, c, m = eng.resolve(opinions)
        print(f"   {method.value:15s} → Winner: {w.value:20s} Confidence: {c:.2%}")

    # 3. Show data structures
    print("\n3️⃣ Data Structures")

    result = ConsensusResult(
        topic="What is the best approach?",
        consensus_answer="Based on multi-agent analysis...",
        confidence=0.81,
        votes=opinions,
        vote_summary={"agree": 2, "strongly_agree": 1, "disagree": 1},
        total_agents=3,
        agreement_percentage=0.667,
    )
    print(f"   ConsensusResult: {result.summary if hasattr(result, 'summary') else 'OK'}")
    print("   Agree: 2, Strongly Agree: 1, Disagree: 1")

    print("\n✅ Swarm Intelligence module ready!")
    print("   (Run with actual LLM-backed agents for real consensus)")


async def demo_router():
    """Demo 3: Multi-Model Router."""
    print("\n" + "=" * 60)
    print("🧠 MULTI-MODEL ROUTER")
    print("=" * 60)

    from ansiq.llm.router import ModelRouter

    router = ModelRouter()

    # Test routing for different task types
    tasks = [
        ("What is 2+2?", "Simple math"),
        ("Summarize this article about AI", "Summarization"),
        ("Write a Python function to sort a list", "Code generation"),
        ("Design a complete microservices architecture", "Complex design"),
        ("Explain the theory of relativity", "Scientific explanation"),
    ]

    print(f"\n{'Task':<50} {'Complexity':<18} {'Model':<30}")
    print("-" * 98)

    for task, task_type in tasks:
        decision = router.route(task)
        print(f"{task_type:<50} {decision.estimated_complexity.value:<18} {decision.selected_model:<30}")
        print(f"{'':>50} {decision.reasoning[:60]}")
        print()

    # List available models
    print("\nRegistered Models:")
    print(f"{'Provider':<15} {'Model':<35} {'Quality':<10} {'Speed':<10} {'Capabilities'}")
    print("-" * 100)
    for model in router.list_models():
        caps = ", ".join(model["capabilities"][:3])
        print(f"{model['provider']:<15} {model['model']:<35} {model['quality']:<10.2f} {model['speed']:<10.2f} {caps}")

    print("\n✅ Multi-Model Router ready!")


async def demo_tool_discovery():
    """Demo 4: Auto-Tool Discovery."""
    print("\n" + "=" * 60)
    print("🔧 AUTO-TOOL DISCOVERY")
    print("=" * 60)

    from ansiq.tools.discover import ansiq_tool, list_discovered_tools

    # Register some example tools
    @ansiq_tool(name="web_search", description="Search the web for information")
    async def web_search(query: str, max_results: int = 10) -> str:
        """Search the web for information.

        Args:
            query: The search query
            max_results: Maximum number of results to return

        Returns:
            Search results as formatted text
        """
        return f"Search results for: {query}"

    @ansiq_tool(name="calculate", description="Perform mathematical calculations")
    async def calculate(expression: str) -> float:
        """Evaluate a mathematical expression.

        Args:
            expression: The mathematical expression to evaluate

        Returns:
            The calculated result
        """
        return eval(expression)

    @ansiq_tool(name="read_file", description="Read contents of a file")
    async def read_file_tool(path: str, encoding: str = "utf-8") -> str:
        """Read a file from the filesystem.

        Args:
            path: Path to the file
            encoding: File encoding (default: utf-8)

        Returns:
            File contents as string
        """
        with open(path, encoding=encoding) as f:
            return f.read()

    # List registered tools
    tools = list_discovered_tools()
    print("\nRegistered Tools:")
    for t in tools:
        print(f"   • {t['name']} ({t['class']})")

    # Show tool details
    from ansiq.tools.discover import _tool_registry
    print("\nTool Details:")
    for name, cls in _tool_registry.items():
        instance = cls()
        print(f"\n   📌 {name}")
        print(f"      Description: {instance.description}")
        print("      Parameters:")
        for param in instance.parameters:
            req = "required" if param.required else "optional"
            print(f"         - {param.name} ({param.type}, {req}): {param.description}")

    print("\n✅ Auto-Tool Discovery ready!")
    print("   (Use @ansiq_tool() decorator on any async function)")


async def demo_parallel_executor():
    """Demo 5: Parallel Executor."""
    print("\n" + "=" * 60)
    print("⚡ PARALLEL EXECUTOR")
    print("=" * 60)

    from ansiq.orchestration.parallel import BatchProcessor, ParallelExecutor, TaskGroup

    # 1. Task Groups
    print("\n1️⃣ Task Groups")

    group = TaskGroup(name="demo_tasks", strict=False)

    async def task_1():
        await asyncio.sleep(0.1)
        return "Task 1 complete"

    async def task_2():
        await asyncio.sleep(0.2)
        return "Task 2 complete"

    async def task_3():
        await asyncio.sleep(0.15)
        return "Task 3 complete"

    group.add(task_1)
    group.add(task_2)
    group.add(task_3)

    print(f"   Group '{group.name}' has {len(group.tasks)} tasks")
    print(f"   Max concurrent: {group.max_concurrent}")
    print(f"   Strict mode: {group.strict}")

    # Execute the group
    results = await group.execute()
    print(f"   Results: {results}")

    # 2. Batch Processor
    print("\n2️⃣ Batch Processor")

    processor = BatchProcessor(max_concurrent=3, retry_count=1)

    async def process_item(item: str) -> str:
        await asyncio.sleep(0.1)
        return f"Processed: {item}"

    items = [f"item_{i}" for i in range(10)]

    def show_progress(completed: int, total: int) -> None:
        if completed % 5 == 0:
            print(f"   Progress: {completed}/{total}")

    batch_results = await processor.process(
        items,
        process_item,
        progress_callback=show_progress,
    )
    print(f"   Completed: {len(batch_results)} items")
    print(f"   Sample: {batch_results[0]}")

    # 3. Parallel Executor
    print("\n3️⃣ Parallel Executor")

    executor = ParallelExecutor(max_workers=5)

    g1 = TaskGroup(name="group_a")
    g1.add(lambda: asyncio.sleep(0.05) or "A1")
    g1.add(lambda: asyncio.sleep(0.05) or "A2")

    g2 = TaskGroup(name="group_b")
    g2.add(lambda: asyncio.sleep(0.05) or "B1")

    all_results = await executor.execute_groups([g1, g2], sequential=False)
    print(f"   All groups completed: {len(all_results)} groups")
    stats = executor.get_stats()
    print(f"   Stats: {stats['total_groups']} groups, {stats['total_tasks']} tasks")

    print("\n✅ Parallel Executor ready!")


async def demo_dag_decorator():
    """Bonus: DAG decorator API."""
    print("\n" + "=" * 60)
    print("🎯 BONUS: DAG DECORATOR API")
    print("=" * 60)

    from ansiq.orchestration.dag import DAG

    dag = DAG("decorator_demo")

    # Using the decorator API
    @dag.task()
    async def fetch_data():
        """Fetch initial data from API."""
        return {"status": "data_fetched"}

    @dag.task(depends_on=[fetch_data])
    async def process_data():
        """Process the fetched data."""
        return {"status": "data_processed"}

    @dag.task(depends_on=[fetch_data])
    async def validate_data():
        """Validate the data integrity."""
        return {"status": "data_validated"}

    @dag.task(depends_on=[process_data, validate_data])
    async def generate_report():
        """Generate final report from processed and validated data."""
        return {"status": "report_generated"}

    print(f"DAG with {len(dag._nodes)} nodes")
    print("\nVisualization:")
    print(dag.visualize())
    print(f"\nExecution order: {[n.name for n in dag._topological_sort()]}")

    # test validation
    try:
        dag._validate()
        print("✓ DAG validation: PASSED")
    except ValueError as e:
        print(f"✗ DAG validation: FAILED - {e}")


async def main():
    print("\n" + "█" * 60)
    print("███  AnsiQ Next-Gen Features — Complete Demo  ███")
    print("█" * 60)
    print("\nThis demo shows all 5 new features WITHOUT requiring LLM calls.")
    print("Each feature is designed to work with or without actual AI models.")
    print("\nFeatures demonstrated:")
    print("   1. DAG Orchestrator — Parallel task execution with deps")
    print("   2. Swarm Intelligence — Agent voting & consensus")
    print("   3. Multi-Model Router — Smart model selection")
    print("   4. Auto-Tool Discovery — @ansiq_tool decorator")
    print("   5. Parallel Executor — Batch & group processing")

    await demo_dag_orchestrator()
    await demo_swarm_intelligence()
    await demo_router()
    await demo_tool_discovery()
    await demo_parallel_executor()
    await demo_dag_decorator()

    print("\n" + "=" * 60)
    print("🎉 ALL DEMOS COMPLETED SUCCESSFULLY!")
    print("=" * 60)
    print("\nAnsiQ is now enhanced with 5 next-gen features:")
    print("  📦 DAG Orchestrator     → Parallel task execution")
    print("  🐝 Swarm Intelligence   → Agent voting & debating")
    print("  🧠 Multi-Model Router   → Smart LLM selection")
    print("  🔧 Auto-Tool Discovery  → @ansiq_tool decorator")
    print("  ⚡ Parallel Executor    → Batch & group processing")
    print("\nTotal new code: ~1,600 lines across 10 new files")
    print("\nNext steps for SaaS product:")
    print("  1. Web UI Dashboard (Streamlit)")
    print("  2. Agent Sandbox (Docker)")
    print("  3. Cost Analytics")
    print("  4. Multi-Tenant API")


if __name__ == "__main__":
    asyncio.run(main())
