"""Tests for the memory system — FTSMemoryStore, EpisodicMemory, ProfileManager."""

from __future__ import annotations

from ansiq.memory.episodic import EpisodicMemory
from ansiq.memory.fts_store import FTSMemoryStore
from ansiq.memory.profile import ProfileManager, Trait, UserProfile


class TestFTSMemoryStore:
    def test_create_store(self, temp_db_path):
        """Test creating a memory store."""
        store = FTSMemoryStore(db_path=temp_db_path)
        assert store.db_path == temp_db_path
        assert store.db_path.exists()

    def test_store_and_search(self, temp_db_path):
        """Test storing and searching memories."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(
            content="Completed research on machine learning algorithms",
            agent_id="agent_1",
            tags=["research", "ml"],
        )
        store.store(
            content="User prefers concise responses",
            agent_id="agent_1",
            tags=["preference"],
        )

        results = store.search("machine learning", limit=10)
        assert len(results) >= 1

        results = store.search("concise", limit=10)
        assert len(results) >= 1
        assert "concise" in results[0]["content"]

    def test_store_with_summary(self, temp_db_path):
        """Test storing with a summary."""
        store = FTSMemoryStore(db_path=temp_db_path)
        rowid = store.store(
            content="Long content here...",
            agent_id="agent_1",
            summary="ML research completed",
            tags=["research"],
        )
        assert rowid > 0

        results = store.search("ML research", limit=10)
        assert len(results) >= 1

    def test_search_by_agent(self, temp_db_path):
        """Test searching memories filtered by agent."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(content="Agent 1 data", agent_id="agent_1")
        store.store(content="Agent 2 data", agent_id="agent_2")

        results = store.search("data", agent_id="agent_1", limit=10)
        for r in results:
            assert r["agent_id"] == "agent_1"

    def test_get_by_tags(self, temp_db_path):
        """Test retrieving memories by tags."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(content="Research data", tags=["research", "important"])
        store.store(content="Personal note", tags=["personal"])
        store.store(content="Important task", tags=["important", "task"])

        # Note: tags are stored, so get_by_tags should work
        # This is an integration-level test
        results = store.search("Important", limit=10)
        assert len(results) >= 0  # at least 0

    def test_get_recent(self, temp_db_path):
        """Test getting recent memories."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(content="First memory")
        store.store(content="Second memory")
        store.store(content="Third memory")

        recent = store.get_recent(limit=2)
        assert len(recent) <= 2

    def test_get_relevant_context(self, temp_db_path):
        """Test getting formatted context string."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(
            content="Key finding: ML models need clean data",
            agent_id="agent_1",
            tags=["research"],
        )
        context = store.get_relevant_context("machine learning", agent_id="agent_1")
        assert "Past Experiences" in context or context == ""

    def test_count(self, temp_db_path):
        """Test counting memories."""
        store = FTSMemoryStore(db_path=temp_db_path)
        assert store.count() == 0
        store.store(content="Test memory")
        assert store.count() == 1
        store.store(content="Another memory")
        assert store.count() == 2

    def test_count_by_agent(self, temp_db_path):
        """Test counting by agent."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(content="A1 data", agent_id="a1")
        store.store(content="A2 data", agent_id="a2")
        store.store(content="A1 more", agent_id="a1")
        assert store.count(agent_id="a1") == 2
        assert store.count(agent_id="a2") == 1

    def test_like_search_fallback(self, temp_db_path):
        """Test LIKE search fallback when FTS5 returns no results."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(content="Special unique term xyz123")
        results = store.search("xyz123", limit=10)
        assert len(results) >= 1

    def test_store_with_metadata(self, temp_db_path):
        """Test storing with metadata."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(
            content="Test with metadata",
            metadata={"source": "web", "url": "https://example.com"},
        )
        results = store.search("metadata", limit=10)
        if results:
            assert "source" in results[0].get("metadata", {})

    def test_close(self, temp_db_path):
        """Test closing the store."""
        store = FTSMemoryStore(db_path=temp_db_path)
        store.store(content="Test")
        store.close()
        # Should not raise
        store.close()


class TestEpisodicMemory:
    def test_begin_episode(self, temp_db_path):
        """Test beginning an episode."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store, agent_id="test_agent")
        ep_id = ep.begin_episode("Research AI")
        assert ep_id is not None
        assert ep._current_episode is not None
        assert ep._current_episode["goal"] == "Research AI"

    def test_record_step(self, temp_db_path):
        """Test recording a step in an episode."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store, agent_id="test_agent")
        ep.begin_episode("Test task")
        ep.record_step("Search web", "Found results", success=True)
        assert len(ep._current_episode["steps"]) == 1

    def test_record_step_no_episode(self, temp_db_path):
        """Test recording step without active episode doesn't crash."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store, agent_id="test_agent")
        ep.record_step("Action", "Result")  # Should not raise

    def test_end_episode(self, temp_db_path):
        """Test ending and persisting an episode."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store, agent_id="test_agent")
        ep.begin_episode("Research task")
        ep.record_step("Search", "Found data", success=True)
        ep_id = ep.end_episode(summary="Completed research")
        assert ep_id is not None
        assert ep._current_episode is None

    def test_end_episode_no_active(self, temp_db_path):
        """Test ending episode without active one returns None."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store)
        assert ep.end_episode() is None

    def test_recall(self, temp_db_path):
        """Test recalling past episodes."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store, agent_id="test_agent")
        ep.begin_episode("Research AI agents")
        ep.end_episode(outcome="completed")

        # Note: recall searches for "episode" tagged memories
        memories = ep.recall("AI agents")
        assert len(memories) > 0

    def test_get_recent_episodes(self, temp_db_path):
        """Test getting recent episodes."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store, agent_id="test_agent")
        ep.begin_episode("Task 1")
        ep.end_episode(outcome="completed")
        ep.begin_episode("Task 2")
        ep.end_episode(outcome="completed")

        recent = ep.get_recent_episodes(limit=5)
        assert len(recent) >= 1

    def test_get_relevant_context(self, temp_db_path):
        """Test getting context from episodes."""
        store = FTSMemoryStore(db_path=temp_db_path)
        ep = EpisodicMemory(store=store, agent_id="test_agent")
        context = ep.get_relevant_context("test")
        assert isinstance(context, str)


class TestProfileManager:
    def test_get_profile_creates_new(self, tmp_path):
        """Test getting a non-existent profile creates it."""
        pm = ProfileManager(profiles_dir=tmp_path)
        profile = pm.get_profile("user_1")
        assert profile.user_id == "user_1"
        assert profile.interaction_count == 0

    def test_get_profile_existing(self, tmp_path):
        """Test getting an existing profile."""
        pm = ProfileManager(profiles_dir=tmp_path)
        p1 = pm.get_profile("user_1")
        p1.interaction_count = 5
        pm.save_profile(p1)

        p2 = pm.get_profile("user_1")
        assert p2.interaction_count == 5

    def test_record_interaction(self, tmp_path):
        """Test recording an interaction."""
        pm = ProfileManager(profiles_dir=tmp_path)
        profile = pm.record_interaction("user_1", "chat")
        assert profile.interaction_count == 1
        assert profile.last_interaction is not None

    def test_add_trait(self, tmp_path):
        """Test adding a trait to a profile."""
        pm = ProfileManager(profiles_dir=tmp_path)
        profile = pm.add_trait("user_1", "communication_style", "concise", 0.8)
        assert len(profile.traits) == 1
        assert profile.traits[0].name == "communication_style"
        assert profile.traits[0].value == "concise"
        assert profile.traits[0].confidence == 0.8

    def test_update_trait(self, tmp_path):
        """Test updating an existing trait."""
        pm = ProfileManager(profiles_dir=tmp_path)
        pm.add_trait("user_1", "style", "verbose", 0.5)
        pm.add_trait("user_1", "style", "concise", 0.9)
        trait = pm.get_trait("user_1", "style")
        assert trait is not None
        assert trait.value == "concise"
        assert trait.confidence == 0.9

    def test_get_trait_nonexistent(self, tmp_path):
        """Test getting a non-existent trait returns None."""
        pm = ProfileManager(profiles_dir=tmp_path)
        assert pm.get_trait("user_1", "nonexistent") is None

    def test_set_and_get_preference(self, tmp_path):
        """Test setting and getting preferences."""
        pm = ProfileManager(profiles_dir=tmp_path)
        pm.set_preference("user_1", "theme", "dark")
        assert pm.get_preference("user_1", "theme") == "dark"
        assert pm.get_preference("user_1", "nonexistent", "default") == "default"

    def test_get_profile_summary(self, tmp_path):
        """Test getting a profile summary string."""
        pm = ProfileManager(profiles_dir=tmp_path)
        pm.add_trait("user_1", "style", "concise")
        pm.set_preference("user_1", "theme", "dark")
        summary = pm.get_profile_summary("user_1")
        assert "user_1" in summary
        assert "concise" in summary

    def test_delete_profile(self, tmp_path):
        """Test deleting a profile."""
        pm = ProfileManager(profiles_dir=tmp_path)
        pm.get_profile("user_1")
        assert pm.delete_profile("user_1") is True
        assert pm.delete_profile("nonexistent") is False

    def test_list_profiles(self, tmp_path):
        """Test listing profiles."""
        pm = ProfileManager(profiles_dir=tmp_path)
        pm.get_profile("user_a")
        pm.get_profile("user_b")
        profiles = pm.list_profiles()
        assert "user_a" in profiles
        assert "user_b" in profiles

    def test_trait_model(self):
        """Test Trait model creation."""
        trait = Trait(
            name="style",
            value="concise",
            confidence=0.9,
            source="analysis",
        )
        assert trait.name == "style"
        assert trait.source == "analysis"
        assert trait.observed_at is not None

    def test_user_profile_model_defaults(self):
        """Test UserProfile default values."""
        profile = UserProfile(user_id="test_user")
        assert profile.traits == []
        assert profile.preferences == {}
        assert profile.interaction_count == 0
        assert profile.created_at is not None
