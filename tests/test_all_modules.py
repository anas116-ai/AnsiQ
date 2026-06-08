"""AnsiQ — Complete Module Test Suite (Core + SaaS).

Tests match the ACTUAL module APIs (verified against source code).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

PASS = 0
FAIL = 0

def _run_test(name: str, func):
    global PASS, FAIL
    try:
        func()
        PASS += 1
        print(f"  ✅ {name}")
    except Exception as e:
        FAIL += 1
        print(f"  ❌ {name}: {e}")


def test_imports():
    """Test all core + SaaS module imports."""
    modules = [
        # Core modules
        "ansiq",
        "ansiq.core.agent",
        "ansiq.core.crew",
        "ansiq.core.task",
        "ansiq.core.flow",
        "ansiq.core.hooks",
        "ansiq.core.state",
        "ansiq.llm.base",
        "ansiq.llm.router",
        "ansiq.brain.reasoning",
        "ansiq.memory.providers",
        "ansiq.tools.base",
        "ansiq.tools.discover",
        "ansiq.orchestration.dag",
        "ansiq.orchestration.parallel",
        "ansiq.swarm.intelligence",
        "ansiq.swarm.consensus",
        "ansiq.swarm.debate",
        "ansiq.ui.components",
        "ansiq.ui.dashboard_pro",
        "ansiq.sandbox.policy",
        "ansiq.analytics.cost_tracker",
        "ansiq.analytics.billing",
        "ansiq.api.tenant",
        "ansiq.api.keys",
        "ansiq.auth.models",
        "ansiq.auth.rbac",
        "ansiq.auth.audit",
        "ansiq.plugins.base",
        "ansiq.plugins.manager",
        "ansiq.evaluation.benchmark",
        "ansiq.evaluation.metrics",
        "ansiq.evaluation.ab_test",
        "ansiq.knowledge.source",
        "ansiq.config.parser",
        "ansiq.embeddings.base",
        "ansiq.execution.executor",
        "ansiq.scheduler.scheduler",
        "ansiq.skills.base",
        "ansiq.skills.registry",
        "ansiq.vectordb.base",
        # SaaS modules
        "saas",
        "saas.config",
    ]
    errors = []
    for m in modules:
        try:
            __import__(m)
        except Exception as e:
            errors.append(f"{m}: {e}")
    if errors:
        for e in errors:
            print(f"  ❌ {e}")
    assert len(errors) == 0, f"{len(errors)} imports failed"


def test_dag():
    """Test DAG creation and visualization."""
    from ansiq.orchestration.dag import DAG, DAGNode
    d = DAG("test")
    d.add_node(DAGNode(id="a", name="A"))
    d.add_node(DAGNode(id="b", name="B", deps=["a"]))
    d.add_node(DAGNode(id="c", name="C", deps=["a"]))
    d.add_node(DAGNode(id="d", name="D", deps=["b", "c"]))
    viz = d.visualize()
    assert "DAG:" in viz
    assert "A" in viz
    assert "B" in viz
    node = d.get_node("a")
    assert node is not None
    assert node.id == "a"


def test_consensus():
    """Test consensus engine with weighted voting."""
    from ansiq.swarm.consensus import ConsensusEngine
    from ansiq.swarm.intelligence import AgentOpinion, VoteType
    opinions = [
        AgentOpinion(agent_name="Alice", agent_role="Engineer", vote=VoteType.STRONGLY_AGREE, confidence=0.9),
        AgentOpinion(agent_name="Bob", agent_role="Analyst", vote=VoteType.AGREE, confidence=0.7),
        AgentOpinion(agent_name="Charlie", agent_role="Critic", vote=VoteType.DISAGREE, confidence=0.5),
    ]
    engine = ConsensusEngine()
    winner, confidence, _ = engine.resolve(opinions)
    assert winner in (VoteType.STRONGLY_AGREE, VoteType.AGREE)
    assert confidence > 0


def test_router():
    """Test model router selects a model."""
    from ansiq.llm.router import ModelRouter
    r = ModelRouter()
    result = r.route("Write Python code")
    assert result.selected_model is not None


def test_tools():
    """Test tool discovery module."""
    from ansiq.tools.discover import list_discovered_tools
    tools = list_discovered_tools()
    assert isinstance(tools, list)


def test_sandbox_policy():
    """Test sandbox command validation."""
    from ansiq.sandbox.policy import SandboxPolicy
    p = SandboxPolicy()
    assert p.validate_command("python --version")


def test_analytics():
    """Test cost tracker recording and summary."""
    import time

    from ansiq.analytics.cost_tracker import CostTracker
    t = CostTracker()
    rec = t.record(
        agent_name="test_agent", model="gpt-4o",
        prompt_tokens=500, completion_tokens=500,
    )
    assert rec is not None
    s = t.get_summary(since=time.time() - 86400 * 30)
    assert s.total_tokens >= 1000
    assert s.total_calls >= 1


def test_plugins():
    """Test plugin manager initialization."""
    from ansiq.plugins.manager import PluginManager
    p = PluginManager()
    assert p.list_plugins() is not None


def test_evaluation():
    """Test quality metrics evaluation."""
    from ansiq.evaluation.metrics import QualityMetrics
    q = QualityMetrics()
    scores = q.evaluate(
        output="Test output about AI systems is working correctly.",
        expected_keywords=["AI", "test", "systems"],
    )
    assert scores["overall_score"] >= 0
    assert scores["overall_score"] <= 1
    assert "accuracy" in scores["metrics"]
    assert "relevance" in scores["metrics"]


def test_password():
    """Test SaaS password hashing."""
    from saas.auth import hash_password, verify_password
    h = hash_password("test123")
    assert verify_password("test123", h) is True
    assert verify_password("wrong", h) is False


def test_saas_config():
    """Test SaaS config singleton."""
    from saas.config import config
    assert config.environment == "development"
    assert config.database.host == "localhost"
    assert config.redis.host == "localhost"


def test_saas_auth():
    """Test JWT token creation and validation."""
    from saas.auth import create_access_token, decode_token, hash_password, verify_password
    pwd = hash_password("secure123")
    assert verify_password("secure123", pwd)
    assert not verify_password("wrong", pwd)
    token = create_access_token("user1", "org1", "owner")
    payload = decode_token(token)
    assert payload["sub"] == "user1"
    assert payload["org"] == "org1"
    assert payload["role"] == "owner"


def test_saas_webhook_signing():
    """Test HMAC-SHA256 webhook signing."""
    from saas.webhooks import sign_payload
    sig = sign_payload(b'{"test":true}', "secret123")
    assert len(sig) == 64
    assert isinstance(sig, str)


def test_saas_models():
    """Test SaaS ORM models init."""
    from saas.models import Organization, OrgPlan, User, UserRole
    org = Organization(name="Test", slug="test-org", plan=OrgPlan.FREE)
    assert org.plan == OrgPlan.FREE
    assert org.name == "Test"
    user = User(email="a@b.com", password_hash="hash", full_name="Test", organization_id="org1", role=UserRole.OWNER)
    assert user.role == UserRole.OWNER


def test_saas_app():
    """Test FastAPI app has routes."""
    from saas.app import app
    assert app.title == "AnsiQ API"
    routes = [r.path for r in app.routes]
    assert "/health" in routes
    assert "/ready" in routes
    assert "/version" in routes


def test_saas_email():
    """Test email service init."""
    from saas.email import EmailMessage, email_service
    assert email_service.from_address == "noreply@ansiq.ai"
    msg = EmailMessage(to="test@test.com", subject="Test", html_body="<p>Hi</p>", text_body="Hi")
    assert msg.to == "test@test.com"


def test_saas_database():
    """Test database config and base model."""
    from saas.database import Base, async_engine
    assert Base is not None
    assert async_engine is not None


# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("AnsiQ — Complete Test Suite (Core + SaaS)")
    print("=" * 60)

    print(f"\n{'─'*60}")
    print("Module Imports")
    print(f"{'─'*60}")
    _run_test("All module imports", test_imports)

    print(f"\n{'─'*60}")
    print("Core Tests")
    print(f"{'─'*60}")
    _run_test("DAG Orchestrator", test_dag)
    _run_test("Swarm Consensus", test_consensus)
    _run_test("Model Router", test_router)
    _run_test("Tool Discovery", test_tools)
    _run_test("Sandbox Policy", test_sandbox_policy)
    _run_test("Cost Analytics", test_analytics)
    _run_test("Plugin System", test_plugins)
    _run_test("Evaluation Framework", test_evaluation)
    _run_test("Password Hashing", test_password)

    print(f"\n{'─'*60}")
    print("SaaS Tests")
    print(f"{'─'*60}")
    _run_test("SaaS Config", test_saas_config)
    _run_test("SaaS Auth (JWT+password)", test_saas_auth)
    _run_test("SaaS Webhook Signing", test_saas_webhook_signing)
    _run_test("SaaS ORM Models", test_saas_models)
    _run_test("SaaS FastAPI App", test_saas_app)
    _run_test("SaaS Email Service", test_saas_email)
    _run_test("SaaS Database", test_saas_database)

    print(f"\n{'═'*60}")
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    print(f"{'═'*60}")
    sys.exit(1 if FAIL > 0 else 0)
