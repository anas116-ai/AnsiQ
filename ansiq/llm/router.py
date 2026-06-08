"""Multi-Model Router — intelligently routes tasks to the best LLM model.

Different tasks have different requirements:
- Simple tasks → cheap/fast models (e.g., GPT-4o-mini, Llama 3.2)
- Complex reasoning → expensive/powerful models (e.g., GPT-4o, Claude 3.5 Sonnet)
- Code generation → code-specialized models
- Creative writing → creative models

The router analyzes each task and selects the optimal model based on:
1. Task complexity (estimated from task description)
2. Required capabilities (reasoning, creativity, code, analysis)
3. Cost constraints
4. Performance requirements (speed vs quality)

This is an original design — CrewAI doesn't have multi-model routing.
"""

from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ansiq.llm.base import LLMProvider, ProviderFactory

logger = logging.getLogger(__name__)


class TaskComplexity(StrEnum):
    """Estimated complexity of a task."""

    SIMPLE = "simple"
    """Basic lookups, formatting, simple Q&A."""

    MEDIUM = "medium"
    """Analysis, summarization, standard reasoning."""

    COMPLEX = "complex"
    """Multi-step reasoning, debate, planning."""

    VERY_COMPLEX = "very_complex"
    """Deep research, code generation, strategic analysis."""


class ModelCapability(StrEnum):
    """Capabilities that models can have."""

    REASONING = "reasoning"
    CREATIVITY = "creativity"
    CODE = "code"
    ANALYSIS = "analysis"
    SPEED = "speed"
    MULTI_MODAL = "multi_modal"
    COST_EFFICIENT = "cost_efficient"
    LONG_CONTEXT = "long_context"


class ModelProfile(BaseModel):
    """Profile for an LLM model with its strengths and costs."""

    provider_name: str
    """The registered provider name (e.g., 'openai', 'anthropic')."""

    model_name: str
    """The model identifier (e.g., 'gpt-4o', 'claude-3-sonnet')."""

    capabilities: list[ModelCapability] = Field(default_factory=list)
    cost_per_1k_input: float = 0.0
    """Cost in USD per 1K input tokens."""

    cost_per_1k_output: float = 0.0
    """Cost in USD per 1K output tokens."""

    speed_rating: float = 0.5
    """0.0 (slow) to 1.0 (fast)."""

    quality_rating: float = 0.5
    """0.0 (low) to 1.0 (high)."""

    max_context: int = 128000
    """Maximum context window in tokens."""

    is_default: bool = False
    """If True, use as fallback when no specialized model matches."""


class RoutingDecision(BaseModel):
    """The result of a routing decision."""

    task_summary: str
    estimated_complexity: TaskComplexity
    selected_provider: str
    selected_model: str
    reasoning: str
    estimated_cost: float = 0.0
    confidence: float = 0.0


class ModelRouter:
    """Routes tasks to the optimal LLM model based on task analysis.

    Features:
    - Automatic task complexity estimation
    - Keyword-based capability detection
    - Cost-aware model selection
    - Fallback chain for reliability
    - Custom model profiles

    Usage:
        router = ModelRouter()
        router.add_model(ModelProfile(
            provider_name="openai",
            model_name="gpt-4o-mini",
            capabilities=[ModelCapability.SPEED, ModelCapability.COST_EFFICIENT],
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            speed_rating=0.9,
        ))
        router.add_model(ModelProfile(
            provider_name="openai",
            model_name="gpt-4o",
            capabilities=[ModelCapability.REASONING, ModelCapability.CODE],
            cost_per_1k_input=0.0025,
            cost_per_1k_output=0.01,
            quality_rating=0.95,
        ))

        decision = router.route("Write a complex Python function")
        provider = router.get_provider(decision)
        response = await provider.chat(messages)
    """

    # Default model profiles (can be extended by user)
    DEFAULT_PROFILES = [
        ModelProfile(
            provider_name="openai",
            model_name="gpt-4o-mini",
            capabilities=[
                ModelCapability.SPEED,
                ModelCapability.COST_EFFICIENT,
                ModelCapability.ANALYSIS,
            ],
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            speed_rating=0.9,
            quality_rating=0.6,
            is_default=False,
        ),
        ModelProfile(
            provider_name="openai",
            model_name="gpt-4o",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.CREATIVITY,
                ModelCapability.MULTI_MODAL,
                ModelCapability.ANALYSIS,
            ],
            cost_per_1k_input=0.0025,
            cost_per_1k_output=0.01,
            speed_rating=0.7,
            quality_rating=0.95,
            max_context=128000,
            is_default=True,
        ),
        ModelProfile(
            provider_name="anthropic",
            model_name="claude-3-5-sonnet-20241022",
            capabilities=[
                ModelCapability.REASONING,
                ModelCapability.CODE,
                ModelCapability.CREATIVITY,
                ModelCapability.ANALYSIS,
                ModelCapability.LONG_CONTEXT,
            ],
            cost_per_1k_input=0.003,
            cost_per_1k_output=0.015,
            speed_rating=0.6,
            quality_rating=0.96,
            max_context=200000,
            is_default=False,
        ),
        ModelProfile(
            provider_name="anthropic",
            model_name="claude-3-haiku-20240307",
            capabilities=[
                ModelCapability.SPEED,
                ModelCapability.COST_EFFICIENT,
                ModelCapability.ANALYSIS,
            ],
            cost_per_1k_input=0.00025,
            cost_per_1k_output=0.00125,
            speed_rating=0.95,
            quality_rating=0.5,
            is_default=False,
        ),
    ]

    def __init__(self):
        self._profiles: list[ModelProfile] = []
        self._provider_cache: dict[str, LLMProvider] = {}
        self._instance_map: dict[str, LLMProvider] = {}

        # Load default profiles
        for profile in self.DEFAULT_PROFILES:
            self.add_model(profile)

    def add_model(self, profile: ModelProfile) -> None:
        """Add a model profile to the router."""
        self._profiles.append(profile)
        logger.debug("Added model: %s/%s", profile.provider_name, profile.model_name)

    def add_custom_provider(
        self,
        name: str,
        provider: LLMProvider,
        profile: ModelProfile,
    ) -> None:
        """Add a custom provider instance with its profile."""
        key = f"{profile.provider_name}/{profile.model_name}"
        self._instance_map[key] = provider
        self._profiles.append(profile)

    def _estimate_complexity(self, task: str) -> TaskComplexity:
        """Estimate task complexity from description."""
        task_lower = task.lower()

        # Very complex indicators
        very_complex_patterns = [
            r"\b(design|architect|strateg(y|ize)|optimize|comprehensive)\b",
            r"\b(multi.?step|complex|sophisticated|intricate)\b",
            r"\b(research|analyze|evaluate|compare|contrast)\b",
            r"\b(generate|create|build|develop)\s+(complex|full|complete)\b",
        ]

        # Complex indicators
        complex_patterns = [
            r"\b(explain|describe|analyze|reason|synthesize)\b",
            r"\b(write|create|generate|implement|code|program)\b",
            r"\b(multiple|several|various|different)\s+(aspects|factors|steps)\b",
            r"\b(debat|argument|perspective|counter)\b",
        ]

        # Medium indicators
        medium_patterns = [
            r"\b(summarize|outline|list|categorize)\b",
            r"\b(compare|contrast|differentiate)\b",
            r"\b(why|how|what\s+if|explain)\b",
        ]

        # Count matches
        very_complex_score = sum(len(re.findall(p, task_lower)) for p in very_complex_patterns)
        complex_score = sum(len(re.findall(p, task_lower)) for p in complex_patterns)
        medium_score = sum(len(re.findall(p, task_lower)) for p in medium_patterns)

        # Simple heuristics
        word_count = len(task.split())
        has_code = bool(re.search(r"(def |class |function|import |from |```)", task))
        has_multiple_questions = task.count("?") > 2
        bool(re.search(r"\d+", task))

        if very_complex_score >= 3 or (complex_score >= 3 and has_code) or word_count > 200:
            return TaskComplexity.VERY_COMPLEX
        elif complex_score >= 2 or has_code or word_count > 100:
            return TaskComplexity.COMPLEX
        elif medium_score >= 1 or has_multiple_questions or word_count > 50:
            return TaskComplexity.MEDIUM
        else:
            return TaskComplexity.SIMPLE

    def _detect_required_capabilities(
        self,
        task: str,
        complexity: TaskComplexity,
    ) -> list[ModelCapability]:
        """Detect which capabilities a task requires."""
        task_lower = task.lower()
        capabilities = set()

        # Reasoning
        if complexity in (TaskComplexity.COMPLEX, TaskComplexity.VERY_COMPLEX):
            capabilities.add(ModelCapability.REASONING)

        # Code
        if re.search(
            r"(def |class |function|import |from |```|\.py|\.js|\.ts|code|program|implement)",
            task_lower,
        ):
            capabilities.add(ModelCapability.CODE)

        # Creativity
        if re.search(r"(creative|write|story|poem|content|blog|article|ad|marketing)", task_lower):
            capabilities.add(ModelCapability.CREATIVITY)

        # Analysis
        if re.search(r"(analy|evaluat|compare|assess|review|audit|investigat)", task_lower):
            capabilities.add(ModelCapability.ANALYSIS)

        # Multi-modal
        if re.search(r"(image|photo|picture|visual|diagram|chart|graph)", task_lower):
            capabilities.add(ModelCapability.MULTI_MODAL)

        # Speed (simple tasks should be fast)
        if complexity == TaskComplexity.SIMPLE:
            capabilities.add(ModelCapability.SPEED)

        # Cost efficiency
        word_count = len(task.split())
        if complexity == TaskComplexity.SIMPLE or word_count > 200:
            capabilities.add(ModelCapability.COST_EFFICIENT)

        return list(capabilities)

    def route(
        self,
        task: str,
        preferred_provider: str | None = None,
        max_cost: float | None = None,
    ) -> RoutingDecision:
        """Route a task to the best model.

        Args:
            task: The task description to analyze
            preferred_provider: Optional preferred provider (e.g., 'openai')
            max_cost: Maximum acceptable cost per request in USD

        Returns:
            RoutingDecision with selected model details
        """
        # Estimate complexity
        complexity = self._estimate_complexity(task)

        # Detect required capabilities
        required_caps = self._detect_required_capabilities(task, complexity)

        # Score each model profile
        scored_profiles: list[tuple[float, ModelProfile, str]] = []

        for profile in self._profiles:
            # Skip if preferred provider specified and doesn't match
            if preferred_provider and profile.provider_name != preferred_provider:
                continue

            # Skip if estimated cost exceeds max_cost
            if max_cost is not None:
                est_tokens = len(task.split()) * 1.5  # rough estimate
                cost = (est_tokens / 1000) * profile.cost_per_1k_input
                if cost > max_cost:
                    continue

            # Calculate capability match score
            cap_score = 0.0
            for required in required_caps:
                if required in profile.capabilities:
                    cap_score += 1.0
                else:
                    cap_score -= 0.3  # Penalty for missing capability

            # Normalize cap score
            if required_caps:
                cap_score /= len(required_caps)
            else:
                cap_score = 0.5

            # Complexity-based scoring

            # For complex tasks, prefer high-quality models
            quality_factor = profile.quality_rating
            if complexity in (TaskComplexity.COMPLEX, TaskComplexity.VERY_COMPLEX):
                quality_factor = profile.quality_rating * 1.5

            # For simple tasks, prefer fast/cheap models
            speed_factor = profile.speed_rating
            if complexity == TaskComplexity.SIMPLE:
                speed_factor = profile.speed_rating * 1.5

            # Default models get a slight bonus
            default_bonus = 0.2 if profile.is_default else 0.0

            # Final score
            total_score = (
                cap_score * 0.4 + quality_factor * 0.3 + speed_factor * 0.2 + default_bonus * 0.1
            )

            scored_profiles.append((total_score, profile, ""))

        if not scored_profiles:
            # Fallback: use the first model available
            if self._profiles:
                profile = self._profiles[0]
                return RoutingDecision(
                    task_summary=task[:100],
                    estimated_complexity=complexity,
                    selected_provider=profile.provider_name,
                    selected_model=profile.model_name,
                    reasoning="Fallback to first available model",
                    confidence=0.3,
                )
            else:
                return RoutingDecision(
                    task_summary=task[:100],
                    estimated_complexity=complexity,
                    selected_provider="openai",
                    selected_model="gpt-4o-mini",
                    reasoning="No models configured, using default fallback",
                    confidence=0.2,
                )

        # Sort by score descending
        scored_profiles.sort(key=lambda x: x[0], reverse=True)
        best_score, best_profile, _ = scored_profiles[0]

        # Generate reasoning
        cap_names = [c.value for c in required_caps]
        reasoning = (
            f"Task complexity: {complexity.value}. "
            f"Required capabilities: {', '.join(cap_names)}. "
            f"Selected '{best_profile.model_name}' "
            f"(quality: {best_profile.quality_rating:.2f}, "
            f"speed: {best_profile.speed_rating:.2f}, "
            f"score: {best_score:.2f})"
        )

        return RoutingDecision(
            task_summary=task[:100],
            estimated_complexity=complexity,
            selected_provider=best_profile.provider_name,
            selected_model=best_profile.model_name,
            reasoning=reasoning,
            estimated_cost=best_profile.cost_per_1k_input,
            confidence=min(best_score, 1.0),
        )

    def get_provider(self, decision: RoutingDecision) -> LLMProvider:
        """Get or create a provider for a routing decision."""
        key = f"{decision.selected_provider}/{decision.selected_model}"

        # Check cache
        if key in self._provider_cache:
            return self._provider_cache[key]

        if key in self._instance_map:
            self._provider_cache[key] = self._instance_map[key]
            return self._instance_map[key]

        # Create new provider
        try:
            provider = ProviderFactory.create(
                decision.selected_provider,
                model=decision.selected_model,
            )
            self._provider_cache[key] = provider
            return provider
        except Exception as e:
            logger.warning(
                "Failed to create provider '%s/%s': %s. Using OpenAI fallback.",
                decision.selected_provider,
                decision.selected_model,
                e,
            )
            fallback = ProviderFactory.create("openai", model="gpt-4o-mini")
            return fallback

    def list_models(self) -> list[dict[str, Any]]:
        """List all registered models with their profiles."""
        return [
            {
                "provider": p.provider_name,
                "model": p.model_name,
                "capabilities": [c.value for c in p.capabilities],
                "quality": p.quality_rating,
                "speed": p.speed_rating,
                "cost_input": p.cost_per_1k_input,
                "cost_output": p.cost_per_1k_output,
                "is_default": p.is_default,
            }
            for p in self._profiles
        ]
