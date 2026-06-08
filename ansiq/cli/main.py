"""CLI main entry point — TUI interface for AnsiQ.

Provides a rich terminal user interface with:
- Interactive chat with agents
- Crew and flow management
- Memory browsing
- Skill management
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ansiq import __version__

console = Console()

# Lazy imports for subcommands
_imports: dict[str, Any] = {}


def _lazy_import(module_path: str, name: str) -> Any:
    """Lazy-import a module to keep startup fast."""
    import importlib

    full_path = f"ansiq.cli.{module_path}"
    if full_path not in _imports:
        _imports[full_path] = importlib.import_module(full_path)
    return getattr(_imports[full_path], name)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with rich handler."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_time=False)],
    )


def print_banner() -> None:
    """Print the AnsiQ banner."""
    banner = Text()
    banner.append("\n")
    banner.append(" █████╗ ███╗   ██╗███████╗██╗ ██████╗\n", style="bold cyan")
    banner.append("██╔══██╗████╗  ██║██╔════╝██║██╔═══╝\n", style="bold cyan")
    banner.append("███████║██╔██╗ ██║███████╗██║██║\n", style="bold cyan")
    banner.append("██╔══██║██║╚██╗██║╚════██║██║██║\n", style="bold cyan")
    banner.append("██║  ██║██║ ╚████║███████║██║╚██████╗\n", style="bold cyan")
    banner.append("╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚═╝ ╚═════╝\n", style="bold cyan")
    banner.append(
        f" v{__version__} — Intelligent Agent Orchestration Framework\n", style="dim white"
    )
    console.print(banner)


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="ansiq",
        description="AnsiQ — Intelligent Agent Orchestration Framework",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AnsiQ v{__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Run a crew from YAML config")
    run_parser.add_argument("config", help="Path to YAML configuration file")
    run_parser.add_argument("-i", "--inputs", nargs="*", help="Input parameters (key=value)")

    # chat command
    chat_parser = subparsers.add_parser("chat", help="Start an interactive chat session")
    chat_parser.add_argument("-m", "--model", default="gpt-4o", help="LLM model to use")
    chat_parser.add_argument("-p", "--provider", default="openai", help="LLM provider")
    chat_parser.add_argument("--local", action="store_true", help="Use local Ollama model")

    # agent command
    agent_parser = subparsers.add_parser("agent", help="Manage agents")
    agent_sub = agent_parser.add_subparsers(dest="agent_command")
    agent_sub.add_parser("list", help="List available agents")
    agent_create = agent_sub.add_parser("create", help="Create a new agent")
    agent_create.add_argument("--role", required=True, help="Agent role")
    agent_create.add_argument("--goal", required=True, help="Agent goal")
    agent_create.add_argument("--backstory", help="Agent backstory")
    agent_create.add_argument("--provider", default="openai", help="LLM provider")
    agent_create.add_argument("--model", default="gpt-4o", help="LLM model")

    # crew command
    crew_parser = subparsers.add_parser("crew", help="Manage crews")
    crew_sub = crew_parser.add_subparsers(dest="crew_command")
    crew_sub.add_parser("list", help="List available crews")
    crew_create = crew_sub.add_parser("create", help="Create a new crew")
    crew_create.add_argument("--name", required=True, help="Crew name")
    crew_create.add_argument("--agents", nargs="+", required=True, help="Agent names/roles")
    crew_create.add_argument("--process", default="pipeline", choices=["pipeline", "council"])

    # memory command
    memory_parser = subparsers.add_parser("memory", help="Browse and manage memory")
    memory_sub = memory_parser.add_subparsers(dest="memory_command")
    memory_sub.add_parser("list", help="List recent memories")
    memory_search = memory_sub.add_parser("search", help="Search memories")
    memory_search.add_argument("query", help="Search query")
    memory_sub.add_parser("stats", help="Memory statistics")

    # skill command
    skill_parser = subparsers.add_parser("skill", help="Manage skills")
    skill_sub = skill_parser.add_subparsers(dest="skill_command")
    skill_sub.add_parser("list", help="List available skills")
    skill_create = skill_sub.add_parser("create", help="Create a new skill")
    skill_create.add_argument("--name", required=True, help="Skill name")
    skill_create.add_argument("--description", required=True, help="Skill description")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the REST API server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    return parser


async def cmd_run(args: argparse.Namespace) -> None:
    """Execute a crew from YAML config."""
    from ansiq.config.parser import ConfigParser

    console.print(f"[bold]Loading config:[/] {args.config}")
    parser = ConfigParser(args.config)
    crew = parser.parse_crew()

    inputs = {}
    if args.inputs:
        for item in args.inputs:
            if "=" in item:
                key, value = item.split("=", 1)
                inputs[key] = value

    console.print(f"[bold]Starting crew execution:[/] {crew}")
    with console.status("[bold green]Executing..."):
        result = await crew.kickoff(inputs=inputs)

    console.print("\n[bold green]✓ Execution complete![/]")
    for i, output in enumerate(result.tasks_output):
        panel = Panel(
            output[:500] + ("..." if len(output) > 500 else ""),
            title=f"Task {i + 1} Output",
            border_style="cyan",
        )
        console.print(panel)


async def cmd_chat(args: argparse.Namespace) -> None:
    """Start an interactive chat session with streaming token display."""
    if args.local:
        args.provider = "ollama"
        args.model = "llama3.2"

    from ansiq.core.agent import Agent, AgentConfig, AgentIdentity
    from ansiq.memory.fts_store import FTSMemoryStore

    agent = Agent(
        identity=AgentIdentity(
            role="AnsiQ Assistant",
            goal="Help the user with their tasks",
            backstory=(
                "An intelligent AI assistant powered by AnsiQ framework. "
                "I can help with coding, research, analysis, and more."
            ),
        ),
        config=AgentConfig(
            llm_provider=args.provider,
            llm_model=args.model,
            llm_api_key=None,
        ),
        memory=FTSMemoryStore(),
    )

    console.print(f"[bold green]AnsiQ Chat[/] ({args.provider}/{args.model})")
    console.print("[dim]Type 'exit' to quit, '/clear' to reset, '/help' for commands[/]\n")

    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory

    history_path = Path.home() / ".ansiq" / "chat_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    session = PromptSession(history=FileHistory(str(history_path)))

    while True:
        try:
            user_input = await session.prompt_async(">> ")
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue

        if user_input.lower() in ("exit", "quit"):
            break
        if user_input.lower() == "/clear":
            agent.reset_conversation()
            console.print("[dim]Conversation cleared[/]")
            continue
        if user_input.lower() == "/help":
            console.print("[bold]Commands:[/]")
            console.print("  exit, quit  - Exit the chat")
            console.print("  /clear      - Clear conversation history")
            console.print("  /help       - Show this help")

            continue

        try:
            # Stream response token by token
            console.print("\n[bold cyan]Assistant:[/] ", end="")
            full_response = ""
            async for token in await agent.chat(user_input, stream=True):
                full_response += token
                console.print(token, end="")
            console.print()  # Newline after response
        except Exception as e:
            console.print(f"[bold red]Error:[/] {e}")


def cmd_agent(args: argparse.Namespace) -> None:
    """Manage agents."""
    if args.agent_command == "list":
        console.print("[bold]Available Agents:[/]")
        console.print("  (No agents configured yet. Use 'ansiq agent create' to add one.)")

    elif args.agent_command == "create":
        from ansiq.config.parser import ConfigWriter
        from ansiq.core.agent import Agent, AgentConfig, AgentIdentity

        identity = AgentIdentity(
            role=args.role,
            goal=args.goal,
            backstory=args.backstory or "",
        )
        config = AgentConfig(
            identity=identity,
            llm_provider=args.provider,
            llm_model=args.model,
        )
        agent = Agent(identity=identity, config=config)

        # Save to config
        config_dir = Path.home() / ".ansiq" / "agents"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{args.role.lower().replace(' ', '_')}.yaml"
        ConfigWriter.write_yaml(
            {args.role.lower().replace(" ", "_"): ConfigWriter.agent_to_dict(agent)},
            config_path,
        )

        console.print(f"[bold green]✓ Agent '{args.role}' created![/]")
        console.print(f"   Config saved to: {config_path}")

    else:
        console.print("[yellow]Use 'ansiq agent list' or 'ansiq agent create'[/]")


def cmd_crew(args: argparse.Namespace) -> None:
    """Manage crews."""
    if args.crew_command == "list":
        console.print("[bold]Available Crews:[/]")
        console.print("  (No crews configured yet. Use 'ansiq crew create' to add one.)")

    elif args.crew_command == "create":
        from ansiq.config.parser import ConfigWriter

        crew_config = {
            "crew": {
                "process": args.process,
                "agents": {
                    agent: {
                        "role": agent,
                        "goal": f"Act as {agent}",
                        "backstory": f"An expert {agent}",
                    }
                    for agent in args.agents
                },
                "tasks": [
                    {
                        "description": f"Task for {agent}",
                        "expected_output": "Completed work",
                        "agent": agent,
                    }
                    for agent in args.agents
                ],
            }
        }

        config_dir = Path.home() / ".ansiq" / "crews"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{args.name}.yaml"
        ConfigWriter.write_yaml(crew_config, config_path)

        console.print(f"[bold green]✓ Crew '{args.name}' created![/]")
        console.print(f"   Config saved to: {config_path}")


async def cmd_memory(args: argparse.Namespace) -> None:
    """Browse and manage memory."""
    from ansiq.memory.fts_store import FTSMemoryStore

    store = FTSMemoryStore()

    if args.memory_command == "list":
        memories = store.get_recent(limit=20)
        if not memories:
            console.print("[yellow]No memories found.[/]")
            return

        table = Table(title="Recent Memories")
        table.add_column("ID", style="dim")
        table.add_column("Timestamp", style="cyan")
        table.add_column("Summary", style="white")

        for mem in memories:
            summary = mem.get("summary", "") or mem.get("content", "")[:60] + "..."
            table.add_row(
                str(mem["rowid"]),
                mem.get("timestamp", "")[:19],
                summary,
            )
        console.print(table)

    elif args.memory_command == "search":
        memories = store.search(args.query, limit=20)
        if not memories:
            console.print("[yellow]No matching memories found.[/]")
            return

        console.print(f"[bold]Search results for:[/] '{args.query}'")
        for mem in memories:
            panel = Panel(
                mem.get("content", ""),
                title=f"Memory #{mem['rowid']} [{mem.get('timestamp', '')[:19]}]",
                border_style="cyan",
            )
            console.print(panel)

    elif args.memory_command == "stats":
        total = store.count()
        console.print("[bold]Memory Statistics:[/]")
        console.print(f"  Total memories: {total}")
        console.print(f"  Database location: {store.db_path}")

    else:
        console.print("[yellow]Use 'ansiq memory list', 'search <query>', or 'stats'[/]")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the REST API server."""
    from ansiq.api.server import run_server

    console.print("[bold green]Starting AnsiQ API server...[/]")
    console.print(f"  Host: [cyan]{args.host}[/]")
    console.print(f"  Port: [cyan]{args.port}[/]")
    console.print(
        f"  Docs: [cyan]http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}/docs[/]"
    )
    run_server(host=args.host, port=args.port, reload=args.reload)


def cmd_skill(args: argparse.Namespace) -> None:
    """Manage skills."""
    if args.skill_command == "list":
        from ansiq.skills.registry import SkillRegistry

        skills = SkillRegistry.list_skills()
        if not skills:
            console.print("[yellow]No skills registered.[/]")
            return

        table = Table(title="Available Skills")
        table.add_column("Name", style="cyan")
        table.add_column("Category", style="dim")
        table.add_column("Version", style="green")
        table.add_column("Description", style="white")

        for skill in skills:
            table.add_row(
                skill.name,
                skill.category,
                skill.version,
                skill.description[:60] + "..."
                if len(skill.description) > 60
                else skill.description,
            )
        console.print(table)

    elif args.skill_command == "create":
        console.print(f"[bold green]✓ Skill '{args.name}' registered![/]")
        console.print("   (Use the skill learner for LLM-generated implementations)")

    else:
        console.print("[yellow]Use 'ansiq skill list' or 'ansiq skill create'[/]")


def main() -> None:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        print_banner()
        console.print("[dim]Use 'ansiq --help' for available commands[/]")
        console.print("\n[bold]Quick start:[/]")
        console.print("  ansiq chat                    Start interactive chat")
        console.print("  ansiq chat --local            Chat with local Ollama model")
        console.print("  ansiq run config.yaml         Run a crew from config")
        console.print("  ansiq agent create --role ... Create a new agent")
        console.print("  ansiq memory stats            View memory statistics")
        return

    setup_logging(args.verbose)

    try:
        if args.command == "run":
            asyncio.run(cmd_run(args))
        elif args.command == "chat":
            asyncio.run(cmd_chat(args))
        elif args.command == "agent":
            cmd_agent(args)
        elif args.command == "crew":
            cmd_crew(args)
        elif args.command == "memory":
            asyncio.run(cmd_memory(args))
        elif args.command == "skill":
            cmd_skill(args)
        elif args.command == "serve":
            cmd_serve(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/] {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
