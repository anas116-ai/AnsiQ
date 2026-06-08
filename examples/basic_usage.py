"""Basic usage examples for AnsiQ framework.

Run: python examples/basic_usage.py
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)


async def demo_agent():
    """Demonstrate creating and using an agent."""
    from ansiq.core.agent import Agent, AgentIdentity

    # Create an agent
    agent = Agent(
        identity=AgentIdentity(
            role="Research Assistant",
            goal="Help find and analyze information",
            backstory="I am an AI assistant specialized in research tasks.",
        ),
        config={
            "llm_provider": "ollama",
            "llm_model": "llama3.2",
            "temperature": 0.5,
        },
    )

    print(f"Agent created: {agent}")
    print(f"Role: {agent.identity.role}")
    print(f"Goal: {agent.identity.goal}")

    # Run a simple task
    # Note: Requires Ollama running with llama3.2 pulled
    # Uncomment to test:
    # response = await agent.run("What are the key features of Python?")
    # print(f"Response: {response.content}")


async def demo_crew():
    """Demonstrate creating and running a crew."""
    from ansiq.core.agent import Agent, AgentIdentity
    from ansiq.core.crew import Crew, ProcessType
    from ansiq.core.task import Task

    # Create agents
    researcher = Agent(
        identity=AgentIdentity(
            role="Researcher",
            goal="Find and summarize information",
            backstory="Expert researcher with years of experience.",
        ),
    )

    writer = Agent(
        identity=AgentIdentity(
            role="Writer",
            goal="Create clear written content",
            backstory="Professional technical writer.",
        ),
    )

    # Create tasks
    research_task = Task(
        description="Research the topic: {topic}",
        expected_output="A research summary",
        agent=researcher,
    )

    writing_task = Task(
        description="Write an article based on the research",
        expected_output="A well-written article",
        agent=writer,
        context=[research_task],
    )

    # Create and run crew
    crew = Crew(
        agents=[researcher, writer],
        tasks=[research_task, writing_task],
        process=ProcessType.PIPELINE,
        verbose=True,
    )

    print(f"Crew created: {crew}")

    # Uncomment to run (requires LLM access):
    # result = await crew.kickoff(inputs={"topic": "Artificial Intelligence"})
    # print(f"Result: {result.raw_output[:500]}")


async def demo_memory():
    """Demonstrate using the memory system."""
    from ansiq.memory.fts_store import FTSMemoryStore

    # Create memory store (uses SQLite FTS5)
    store = FTSMemoryStore()

    # Store some memories
    store.store(
        content="Completed task: Research on machine learning algorithms",
        agent_id="agent_1",
        summary="ML research completed",
        tags=["research", "machine_learning"],
    )

    store.store(
        content="User prefers concise responses with bullet points",
        agent_id="agent_1",
        tags=["preference", "communication"],
    )

    # Search memories
    results = store.search("machine learning", limit=5)
    print(f"\nMemory search results: {len(results)}")
    for r in results:
        print(f"  - [{r['timestamp'][:19]}] {r['content'][:80]}...")

    # Get recent memories
    recent = store.get_recent(limit=5)
    print(f"\nRecent memories: {len(recent)}")

    # Memory stats
    print(f"\nTotal memories: {store.count()}")


async def demo_flow():
    """Demonstrate a simple event-driven flow."""
    from ansiq.core.flow import Flow, listen, start

    class ResearchFlow(Flow):
        """A flow that researches and summarizes a topic."""

        @start()
        async def research(self, topic: str = "AI"):
            """Research the topic."""
            return {"findings": f"Research findings about {topic}"}

        @listen(research)
        async def summarize(self, findings):
            """Summarize the research findings."""
            return {"summary": f"Summary: {findings.get('findings', 'No findings')}"}

        @listen(summarize)
        async def format_output(self, summary):
            """Format the final output."""
            return {"final": f"## Report\n\n{summary.get('summary', '')}"}

    flow = ResearchFlow()
    result = await flow.kickoff({"topic": "Quantum Computing"})
    print(f"\nFlow methods: {flow.get_methods()}")
    print(f"Flow outputs: {list(result.keys())}")


async def main():
    print("=" * 60)
    print("AnsiQ Framework — Basic Usage Examples")
    print("=" * 60)

    print("\n1. Agent Demo")
    print("-" * 40)
    await demo_agent()

    print("\n2. Crew Demo")
    print("-" * 40)
    await demo_crew()

    print("\n3. Memory Demo")
    print("-" * 40)
    await demo_memory()

    print("\n4. Flow Demo")
    print("-" * 40)
    await demo_flow()

    print("\n" + "=" * 60)
    print("All demos completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
