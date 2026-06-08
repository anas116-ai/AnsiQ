"""Tests for the skill system — BaseSkill, SkillRegistry, SkillLearner."""

from __future__ import annotations

import pytest

from ansiq.skills.base import BaseSkill, SkillResult
from ansiq.skills.learner import DynamicSkill, SkillLearner
from ansiq.skills.registry import SkillRegistry


class TestBaseSkill:
    def test_default_name(self):
        """Test skill gets default name from class name."""

        class MyTestSkill(BaseSkill):
            description = "A test skill"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="done")

        skill = MyTestSkill()
        assert skill.name == "mytestskill"

    def test_custom_name(self):
        """Test skill with custom name."""

        class CustomSkill(BaseSkill):
            name = "custom_skill"
            description = "A custom skill"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="custom")

        skill = CustomSkill()
        assert skill.name == "custom_skill"

    def test_execute(self):
        """Test skill execution."""

        class GreetSkill(BaseSkill):
            name = "greet"
            description = "Greets someone"

            async def execute(self, name: str = "World") -> SkillResult:
                return SkillResult(output=f"Hello, {name}!")

        import asyncio

        skill = GreetSkill()
        result = asyncio.run(skill.execute(name="Test"))
        assert result.success
        assert result.output == "Hello, Test!"

    def test_run_convenience(self):
        """Test run convenience method."""

        class SimpleSkill(BaseSkill):
            name = "simple"
            description = "Simple skill"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="done")

        import asyncio

        skill = SimpleSkill()
        output = asyncio.run(skill.run())
        assert output == "done"

    def test_improve(self):
        """Test recording improvement feedback."""

        class TestSkill(BaseSkill):
            name = "test"
            description = "Test"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="ok")

        skill = TestSkill()
        skill.improve("Make it faster")
        skill.improve("Add error handling")
        assert len(skill.get_improvement_history()) == 2
        assert skill.get_execution_count() == 2

    def test_to_dict(self):
        """Test serializing skill to dict."""

        class TestSkill(BaseSkill):
            name = "test_skill"
            description = "A test skill"
            version = "2.0.0"
            category = "testing"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="ok")

        skill = TestSkill()
        d = skill.to_dict()
        assert d["name"] == "test_skill"
        assert d["version"] == "2.0.0"
        assert d["category"] == "testing"


class TestSkillRegistry:
    def setup_method(self):
        SkillRegistry._skills.clear()

    def test_register_and_get(self):
        """Test registering and retrieving a skill."""

        class TestSkill(BaseSkill):
            name = "my_skill"
            description = "My skill"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="ok")

        skill = TestSkill()
        SkillRegistry.register(skill)
        retrieved = SkillRegistry.get("my_skill")
        assert retrieved is not None
        assert retrieved.name == "my_skill"

    def test_register_class(self):
        """Test registering a skill class."""

        class TestSkill(BaseSkill):
            name = "class_skill"
            description = "From class"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="ok")

        SkillRegistry.register_class(TestSkill)
        assert SkillRegistry.get("class_skill") is not None

    def test_unregister(self):
        """Test unregistering a skill."""

        class TestSkill(BaseSkill):
            name = "remove_me"
            description = "To be removed"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="ok")

        SkillRegistry.register_class(TestSkill)
        SkillRegistry.unregister("remove_me")
        assert SkillRegistry.get("remove_me") is None

    def test_list_skills(self):
        """Test listing all registered skills."""

        class S1(BaseSkill):
            name = "s1"
            description = "S1"
            async def execute(self, **kwargs): return SkillResult()

        class S2(BaseSkill):
            name = "s2"
            description = "S2"
            async def execute(self, **kwargs): return SkillResult()

        SkillRegistry.register_class(S1)
        SkillRegistry.register_class(S2)
        assert len(SkillRegistry.list_skills()) == 2

    def test_list_by_category(self):
        """Test listing skills by category."""

        class DevSkill(BaseSkill):
            name = "dev"
            description = "Dev skill"
            category = "development"
            async def execute(self, **kwargs): return SkillResult()

        class DataSkill(BaseSkill):
            name = "data"
            description = "Data skill"
            category = "analytics"
            async def execute(self, **kwargs): return SkillResult()

        SkillRegistry.register_class(DevSkill)
        SkillRegistry.register_class(DataSkill)
        dev_skills = SkillRegistry.list_by_category("development")
        assert len(dev_skills) == 1
        assert dev_skills[0].name == "dev"

    def test_search(self):
        """Test searching skills by name/description."""

        class SearchSkill(BaseSkill):
            name = "data_analysis"
            description = "Analyze data and find patterns"
            async def execute(self, **kwargs): return SkillResult()

        SkillRegistry.register_class(SearchSkill)
        results = SkillRegistry.search("analysis")
        assert len(results) >= 1

    def test_get_skill_map(self):
        """Test getting skill map summary."""

        class MapSkill(BaseSkill):
            name = "map_skill"
            description = "Mapped"
            category = "test"
            async def execute(self, **kwargs): return SkillResult()

        SkillRegistry.register_class(MapSkill)
        skill_map = SkillRegistry.get_skill_map()
        assert "map_skill" in skill_map
        assert skill_map["map_skill"]["category"] == "test"


class TestDynamicSkill:
    def test_create_dynamic_skill(self):
        """Test creating a dynamic skill."""
        skill = DynamicSkill(
            name="dynamic_test",
            description="A dynamically created skill",
            implementation="result = 'dynamic execution'",
        )
        assert skill.name == "dynamic_test"
        assert skill.description == "A dynamically created skill"

    def test_execute_dynamic_skill(self):
        """Test executing a dynamic skill."""
        skill = DynamicSkill(
            name="exec_test",
            description="Test execution",
            implementation="""
name = kwargs.get('name', 'unknown')
result = f'Executed {name}'
""",
        )
        import asyncio

        result = asyncio.run(skill.execute(name="test"))
        assert result.success
        assert "test" in result.output or "Executed" in result.output

    def test_dynamic_skill_failure(self):
        """Test dynamic skill handles execution errors."""
        skill = DynamicSkill(
            name="failing",
            description="Fails",
            implementation="raise ValueError('Bad')",
        )
        import asyncio

        result = asyncio.run(skill.execute())
        assert not result.success
        assert "Bad" in result.error


class TestSkillLearner:
    @pytest.mark.asyncio
    async def test_create_skill_without_llm(self):
        """Test creating a skill without an LLM falls back gracefully."""
        learner = SkillLearner()
        skill = await learner.create_skill(
            name="simple_skill",
            description="A simple skill",
        )
        assert skill is not None
        assert skill.name == "simple_skill"

    @pytest.mark.asyncio
    async def test_improve_skill(self):
        """Test improving a skill records feedback."""
        learner = SkillLearner()
        skill = DynamicSkill(
            name="improvable",
            description="Can be improved",
            implementation="result = 'original'",
        )
        improved = await learner.improve_skill(skill, "Make it better")
        assert len(improved.get_improvement_history()) == 1

    @pytest.mark.asyncio
    async def test_learn_from_demonstration_without_llm(self):
        """Test learning from demonstration without LLM."""
        learner = SkillLearner()
        skill = await learner.learn_from_demonstration(
            "To do X, first do Y, then do Z",
            "learned_skill",
        )
        assert skill is not None
        assert skill.name == "learned_skill"
