# AnsiQ — Intelligent Agent Orchestration Framework

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

**AnsiQ** is a unified open-source framework that combines **multi-agent orchestration**, **persistent memory**, **autonomous skill learning**, **cross-platform messaging**, and **universal LLM support** — including local models via Ollama, cloud APIs (OpenAI, Anthropic, OpenRouter), and HuggingFace.

> Inspired by the best features of CrewAI (multi-agent orchestration) and Hermes Agent (persistent agent with memory/skills), AnsiQ brings them together in a clean, extensible architecture.

## Features

### 🧠 Multi-Agent Orchestration
- **Pipeline Process** — Sequential task execution with context passing
- **Council Process** — Hierarchical coordination with a manager agent
- **Event-Driven Flows** — Decorator-based workflow engine (`@start`, `@listen`, `@router`)
- **State Management** — Type-safe Pydantic state across flow steps
- **Conditional Branching** — `or_()` and `and_()` combinators for complex workflows

### 🤖 Universal LLM Support
- **Local Models** — Ollama (no API key needed)
- **Cloud APIs** — OpenAI, Anthropic Claude, OpenRouter
- **Open Source** — HuggingFace Inference API
- **Custom Providers** — Extend via `LLMProvider` abstract base class
- **Automatic Fallback** — Graceful degradation if provider fails

### 💾 Persistent Memory
- **FTS5 Full-Text Search** — SQLite-based fast memory retrieval
- **Episodic Memory** — Timeline of experiences with LLM-summarized compressions
- **User Profiles** — Learn preferences and behavior patterns over time
- **Tag-Based Organization** — Categorize and filter memories

### 🛠 Tool System
- **Built-in Tools** — File operations, web search/fetch, code execution
- **Tool Registry** — Global registry for discoverable tools
- **MCP Support Ready** — Architecture supports Model Context Protocol integration
- **Custom Tools** — Extend via `BaseTool` abstract class

### 🎯 Skill System
- **Autonomous Creation** — LLM generates skills from natural language descriptions
- **Skill Improvement** — Refine skills based on execution feedback
- **Dynamic Skills** — Runtime-generated capabilities
- **Skill Registry** — Central registry for discovery

### 📡 Cross-Platform Messaging
- **Telegram** — Full bot API integration
- **Discord** — Bot with message content intent
- **Slack** — RTM and Web API integration
- **Unified Interface** — Common `Message` model across platforms

### 🔒 Execution Environments
- **Local** — Subprocess execution with timeout
- **Docker** — Isolated container execution
- **SSH** — Remote machine execution

### ⏰ Scheduler
- **Cron-Based** — Standard 5-field cron expressions
- **Persistent** — Schedules saved to disk
- **Error Handling** — Automatic retry and logging

### 📝 YAML Configuration
- **Declarative Setup** — Define agents, crews, and tasks in YAML
- **Include Support** — Compose configurations from multiple files
- **CLI-Driven** — Run crews directly from config files

## Quick Start

### Installation

```bash
# Install with uv (recommended)
uv pip install -e .

# Install with pip
pip install -e .

# Install with all extras
pip install -e ".[all]"

# Install specific extras
pip install -e ".[openai,ollama]"
pip install -e ".[telegram,discord,slack]"
pip install -e ".[docker,ssh]"
```

### Basic Usage

```python
from ansiq.core.agent import Agent, AgentIdentity
from ansiq.core.crew import Crew, ProcessType
from ansiq.core.task import Task

# Create agents
researcher = Agent(
    identity=AgentIdentity(
        role="Senior Researcher",
        goal="Find comprehensive information on any topic",
        backstory="Expert researcher with years of experience.",
    ),
)

writer = Agent(
    identity=AgentIdentity(
        role="Technical Writer",
        goal="Create clear, engaging content",
        backstory="Professional writer specializing in technical topics.",
    ),
)

# Define tasks
research = Task(
    description="Research the topic: {topic}",
    expected_output="Research summary",
    agent=researcher,
)

write = Task(
    description="Write article based on research findings",
    expected_output="Polished article",
    agent=writer,
    context=[research],
)

# Run the crew
crew = Crew(
    agents=[researcher, writer],
    tasks=[research, write],
    process=ProcessType.PIPELINE,
)

result = await crew.kickoff(inputs={"topic": "AI Agents"})
print(result.raw_output)
```

### CLI Usage

```bash
# Start interactive chat
ansiq chat

# Chat with local model
ansiq chat --local

# Run a crew from config
ansiq run config/research_crew.yaml -i topic="AI" depth=detailed

# Manage agents
ansiq agent create --role "Researcher" --goal "Find information" --model gpt-4o

# Browse memory
ansiq memory list
ansiq memory stats
ansiq memory search "machine learning"

# Manage skills
ansiq skill list
```

### YAML Configuration

```yaml
# config/crew.yaml
crew:
  name: research_crew
  process: pipeline
  agents:
    researcher:
      role: Senior Researcher
      goal: Find comprehensive information
      backstory: Expert researcher
      llm_provider: ollama
      llm_model: llama3.2
  tasks:
    - description: Research {topic}
      expected_output: Summary
      agent: researcher
```

## Architecture

```
ansiq/
├── __init__.py              # Package root
├── core/                    # Core orchestration engine
│   ├── agent.py             # Agent — role, tools, memory, LLM
│   ├── task.py              # Task — unit of work
│   ├── crew.py              # Crew — multi-agent orchestration
│   ├── flow.py              # Flow — event-driven workflow
│   └── state.py             # State — type-safe state management
├── llm/                     # LLM provider abstraction
│   ├── base.py              # ProviderFactory, LLMMessage, etc.
│   ├── openai_provider.py   # OpenAI / OpenRouter
│   ├── ollama_provider.py   # Local Ollama models
│   ├── anthropic_provider.py# Anthropic Claude
│   └── huggingface_provider.py # HuggingFace
├── memory/                  # Persistent memory system
│   ├── fts_store.py         # FTS5 full-text search
│   ├── episodic.py          # Episode-based memory
│   └── profile.py           # User profile modeling
├── skills/                  # Skill system
│   ├── base.py              # BaseSkill abstract class
│   ├── registry.py          # Skill registry
│   └── learner.py           # LLM-based skill creation
├── tools/                   # Tool system
│   ├── base.py              # BaseTool abstract class
│   ├── registry.py          # Tool registry
│   └── builtin/             # Built-in tools
├── config/                  # YAML configuration
│   └── parser.py            # YAML → AnsiQ objects
├── cli/                     # CLI and TUI
│   └── main.py              # Rich terminal interface
├── gateway/                 # Messaging gateways
│   └── gateway.py           # Telegram, Discord, Slack
├── execution/               # Execution environments
│   └── executor.py          # Local, Docker, SSH
└── scheduler/               # Task scheduler
    └── scheduler.py         # Cron-based scheduling
```

## Requirements

- Python 3.11+
- For local models: [Ollama](https://ollama.ai/) with pulled models
- For Docker execution: Docker daemon
- For messaging gateways: Bot tokens (Telegram, Discord, Slack)

## Extras

| Extra | Install | Required For |
|-------|---------|-------------|
| `openai` | `pip install 'ansiq[openai]'` | OpenAI API |
| `ollama` | (built-in) | Local Ollama models |
| `anthropic` | `pip install 'ansiq[anthropic]'` | Claude API |
| `huggingface` | `pip install 'ansiq[huggingface]'` | HuggingFace API |
| `telegram` | `pip install 'ansiq[telegram]'` | Telegram bot |
| `discord` | `pip install 'ansiq[discord]'` | Discord bot |
| `slack` | `pip install 'ansiq[slack]'` | Slack bot |
| `docker` | `pip install 'ansiq[docker]'` | Docker execution |
| `ssh` | `pip install 'ansiq[ssh]'` | SSH execution |
| `all` | `pip install 'ansiq[all]'` | Everything |
| `dev` | `pip install 'ansiq[dev]'` | Development |

## License

MIT License — see [LICENSE](LICENSE) for details.
