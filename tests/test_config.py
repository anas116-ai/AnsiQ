"""Tests for the YAML configuration system."""

from __future__ import annotations

import pytest

from ansiq.config.parser import ConfigParser, ConfigWriter
from ansiq.core.agent import Agent, AgentIdentity
from ansiq.core.crew import Crew, ProcessType
from ansiq.core.task import Task

SAMPLE_YAML = """
agents:
  researcher:
    role: Senior Researcher
    goal: Find information on {topic}
    backstory: Expert researcher
    llm_provider: openai
    llm_model: gpt-4o
    temperature: 0.5

  writer:
    role: Technical Writer
    goal: Write about {topic}
    backstory: Expert writer
    llm_provider: ollama
    llm_model: llama3.2

tasks:
  - description: Research the topic {topic}
    expected_output: Research summary
    agent: researcher

  - description: Write an article about {topic}
    expected_output: Polished article
    agent: writer
    context:
      - Research the topic {topic}

crew:
  process: pipeline
  verbose: true
"""


class TestConfigParser:
    def test_parse_agents(self):
        """Test parsing agents from YAML."""
        parser = ConfigParser.from_string(SAMPLE_YAML)
        agents = parser.parse_agents()

        assert len(agents) >= 2
        assert "researcher" in agents
        assert "writer" in agents

        researcher = agents["researcher"]
        assert researcher.identity.role == "Senior Researcher"
        assert researcher.config.llm_model == "gpt-4o"

        writer = agents["writer"]
        assert writer.identity.role == "Technical Writer"
        assert writer.config.llm_provider == "ollama"

    def test_parse_tasks(self):
        """Test parsing tasks from YAML."""
        parser = ConfigParser.from_string(SAMPLE_YAML)
        agents = parser.parse_agents()
        tasks = parser.parse_tasks(agents)

        assert len(tasks) >= 1
        assert "Research" in tasks[0].description
        assert tasks[0].expected_output == "Research summary"

    def test_parse_crew(self):
        """Test parsing a complete crew from YAML."""
        parser = ConfigParser.from_string(SAMPLE_YAML)
        crew = parser.parse_crew()

        assert isinstance(crew, Crew)
        assert len(crew.agents) >= 2
        assert len(crew.tasks) >= 1
        assert crew.process == ProcessType.PIPELINE

    def test_parse_flow_inputs(self):
        """Test parsing flow inputs."""
        parser = ConfigParser.from_string("inputs:\n  topic: AI\n  depth: detailed")
        inputs = parser.parse_flow_inputs()
        assert inputs.get("topic") == "AI"
        assert inputs.get("depth") == "detailed"

    def test_empty_inputs(self):
        """Test parse flow inputs with no inputs."""
        parser = ConfigParser.from_string("crew:\n  process: pipeline")
        inputs = parser.parse_flow_inputs()
        assert inputs == {}

    def test_load_yaml_file_not_found(self):
        """Test loading non-existent file raises error."""
        with pytest.raises(FileNotFoundError):
            ConfigParser("/nonexistent/path/config.yaml")


class TestConfigWriter:
    def test_agent_to_dict(self):
        """Test serializing an agent to dict."""
        identity = AgentIdentity(
            role="Test Agent",
            goal="Test goal",
            backstory="Test backstory",
        )
        agent = Agent(identity=identity)
        d = ConfigWriter.agent_to_dict(agent)
        assert d["role"] == "Test Agent"
        assert d["goal"] == "Test goal"
        assert d["llm_model"] is not None

    def test_task_to_dict(self):
        """Test serializing a task to dict."""
        identity = AgentIdentity(
            role="Agent", goal="Goal", backstory="Story"
        )
        agent = Agent(identity=identity)
        task = Task(
            description="Do something",
            expected_output="Result",
            agent=agent,
        )
        d = ConfigWriter.task_to_dict(task)
        assert d["description"] == "Do something"
        assert d["agent"] == "Agent"

    def test_task_to_dict_no_agent(self):
        """Test task without agent."""
        task = Task(
            description="Do something",
            expected_output="Result",
        )
        d = ConfigWriter.task_to_dict(task)
        assert d["agent"] is None

    def test_crew_to_dict(self):
        """Test serializing a crew to dict."""
        agent = Agent(
            identity=AgentIdentity(
                role="Worker", goal="Work", backstory="Works hard."
            ),
        )
        task = Task(
            description="Work task",
            expected_output="Done",
            agent=agent,
        )
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=ProcessType.COUNCIL,
        )
        d = ConfigWriter.crew_to_dict(crew)
        assert "crew" in d
        assert d["crew"]["process"] == "council"
