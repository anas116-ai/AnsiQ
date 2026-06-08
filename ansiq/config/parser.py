"""YAML Configuration system for agents, crews, and tasks.

Enables declarative configuration via YAML files,
similar to CrewAI's configuration approach but unified.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import yaml

from ansiq.core.agent import Agent, AgentConfig, AgentIdentity
from ansiq.core.crew import Crew, ProcessType
from ansiq.core.task import Task

logger = logging.getLogger(__name__)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load and parse a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def resolve_includes(config: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Resolve !include directives in YAML config."""
    if isinstance(config, dict):
        resolved = {}
        for key, value in config.items():
            if isinstance(value, dict) and "!include" in value:
                include_path = base_dir / value["!include"]
                included = load_yaml(include_path)
                resolved[key] = included
            else:
                resolved[key] = resolve_includes(value, base_dir)
        return resolved
    elif isinstance(config, list):
        return [resolve_includes(item, base_dir) for item in config]
    return config


class ConfigParser:
    """Parses YAML configuration into AnsiQ objects.

    Supports agent, task, crew, and flow configurations.
    """

    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent
        self.raw_config = load_yaml(self.config_path)
        self.raw_config = resolve_includes(self.raw_config, self.base_dir)

    def parse_agents(self) -> dict[str, Agent]:
        """Parse agent definitions from config."""
        agents = {}
        agents_config = self.raw_config.get("agents", {})

        for name, cfg in agents_config.items():
            identity = AgentIdentity(
                role=cfg.get("role", name),
                goal=cfg.get("goal", ""),
                backstory=cfg.get("backstory", ""),
            )

            agent_config = AgentConfig(
                identity=identity,
                llm_provider=cfg.get("llm_provider", "openai"),
                llm_model=cfg.get("llm_model", "gpt-4o"),
                llm_api_key=cfg.get("llm_api_key"),
                llm_base_url=cfg.get("llm_base_url"),
                temperature=cfg.get("temperature", 0.7),
                max_tokens=cfg.get("max_tokens", 4096),
                allow_delegation=cfg.get("allow_delegation", False),
                verbose=cfg.get("verbose", False),
            )

            agent = Agent(identity=identity, config=agent_config)
            agents[name] = agent
            logger.debug("Parsed agent: %s", name)

        return agents

    def parse_tasks(
        self,
        agents: dict[str, Agent] | None = None,
    ) -> list[Task]:
        """Parse task definitions from config."""
        tasks = []
        tasks_config = self.raw_config.get("tasks", [])

        for cfg in tasks_config:
            task = Task(
                description=cfg.get("description", ""),
                expected_output=cfg.get("expected_output", ""),
                agent=cfg.get("agent"),  # Will be assigned later
                output_file=cfg.get("output_file"),
                human_input=cfg.get("human_input", False),
                allow_delegation=cfg.get("allow_delegation", False),
                async_execution=cfg.get("async_execution", False),
            )

            # Resolve context task references
            context_refs = cfg.get("context", [])
            if context_refs and agents:
                task.context = [t for t in tasks if t.description in context_refs]

            tasks.append(task)

        return tasks

    def parse_crew(self) -> Crew:
        """Parse a complete crew configuration.

        Example YAML:
        ```yaml
        crew:
          name: research_crew
          process: pipeline
          agents:
            researcher:
              role: Senior Researcher
              goal: Find information
              backstory: Expert researcher
            analyst:
              role: Data Analyst
              goal: Analyze findings
              backstory: Expert analyst
          tasks:
            - description: Research the topic {topic}
              expected_output: Research report
              agent: researcher
            - description: Analyze the research
              expected_output: Analysis report
              agent: analyst
        ```
        """
        crew_cfg = self.raw_config.get("crew", self.raw_config)
        agents = self.parse_agents()
        tasks = self.parse_tasks(agents)

        # Assign agents to tasks
        for task in tasks:
            if task.agent and isinstance(task.agent, str):
                agent_name = task.agent
                if agent_name in agents:
                    task.agent = agents[agent_name]

        process_type = ProcessType(crew_cfg.get("process", "pipeline"))

        # Find manager agent if specified
        manager_name = crew_cfg.get("manager_agent")
        manager_agent = agents.get(manager_name) if manager_name else None

        crew = Crew(
            agents=list(agents.values()),
            tasks=tasks,
            process=process_type,
            manager_agent=manager_agent,
            verbose=crew_cfg.get("verbose", False),
        )

        return crew

    def parse_flow_inputs(self) -> dict[str, Any]:
        """Parse flow input parameters from config."""
        return self.raw_config.get("inputs", {})

    @classmethod
    def from_string(cls, yaml_content: str) -> ConfigParser:
        """Create a ConfigParser from a YAML string."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = f.name
        return cls(tmp_path)

    def __del__(self):
        """Clean up any temporary files created by from_string()."""
        if hasattr(self, "config_path") and self.config_path:
            try:
                if self.config_path.exists():
                    self.config_path.unlink()
            except Exception:
                pass


class ConfigWriter:
    """Writes AnsiQ objects to YAML configuration files."""

    @staticmethod
    def agent_to_dict(agent: Agent) -> dict[str, Any]:
        """Serialize an agent to a config dictionary."""
        return {
            "role": agent.identity.role,
            "goal": agent.identity.goal,
            "backstory": agent.identity.backstory,
            "llm_provider": agent.config.llm_provider,
            "llm_model": agent.config.llm_model,
            "temperature": agent.config.temperature,
            "max_tokens": agent.config.max_tokens,
            "allow_delegation": agent.config.allow_delegation,
            "verbose": agent.config.verbose,
        }

    @staticmethod
    def task_to_dict(task: Task) -> dict[str, Any]:
        """Serialize a task to a config dictionary."""
        return {
            "description": task.description,
            "expected_output": task.expected_output,
            "agent": task.agent.identity.role if hasattr(task.agent, "identity") else None,
            "output_file": task.output_file,
            "human_input": task.human_input,
            "async_execution": task.async_execution,
        }

    @staticmethod
    def crew_to_dict(crew: Crew) -> dict[str, Any]:
        """Serialize a crew to a config dictionary."""
        agents_config = {}
        for agent in crew.agents:
            agents_config[agent.identity.role.lower().replace(" ", "_")] = (
                ConfigWriter.agent_to_dict(agent)
            )

        return {
            "crew": {
                "process": crew.process.value,
                "verbose": crew.verbose,
                "agents": agents_config,
                "tasks": [ConfigWriter.task_to_dict(t) for t in crew.tasks],
            }
        }

    @staticmethod
    def write_yaml(data: dict[str, Any], path: str | Path) -> None:
        """Write a dictionary to a YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info("Wrote config to: %s", path)
