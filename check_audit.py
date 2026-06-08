"""AnsiQ - Production Audit Check
Verifies environment variables, module imports, core functionality,
and returns a comprehensive health report.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

# -- Configuration -----------------------------------------------------

REQUIRED_ENV_VARS = [
    "ANSIQ_DEBUG",
    "ANSIQ_ENV",
    "ANSIQ_JWT_SECRET",
]

CORE_MODULES = [
    "ansiq", "ansiq.core.agent", "ansiq.core.crew", "ansiq.core.task",
    "ansiq.core.flow", "ansiq.core.hooks", "ansiq.core.state",
    "ansiq.llm.base", "ansiq.llm.router", "ansiq.brain.reasoning",
    "ansiq.memory.providers", "ansiq.memory.fts_store",
    "ansiq.tools.base", "ansiq.tools.discover", "ansiq.tools.registry",
    "ansiq.orchestration.dag", "ansiq.orchestration.parallel",
    "ansiq.swarm.intelligence", "ansiq.swarm.consensus", "ansiq.swarm.debate",
    "ansiq.sandbox.docker", "ansiq.sandbox.policy",
    "ansiq.analytics.cost_tracker", "ansiq.analytics.billing",
    "ansiq.api.server", "ansiq.api.tenant", "ansiq.api.keys", "ansiq.api.auth",
    "ansiq.auth.models", "ansiq.auth.rbac", "ansiq.auth.audit",
    "ansiq.plugins.base", "ansiq.plugins.manager",
    "ansiq.evaluation.benchmark", "ansiq.evaluation.metrics", "ansiq.evaluation.ab_test",
    "ansiq.knowledge.engine", "ansiq.knowledge.source", "ansiq.knowledge.store",
    "ansiq.config.parser", "ansiq.embeddings.base",
    "ansiq.execution.executor", "ansiq.scheduler.scheduler",
    "ansiq.skills.base", "ansiq.skills.registry",
    "ansiq.vectordb.base", "ansiq.vectordb.chroma_provider",
    "ansiq.ui.components", "ansiq.ui.dashboard_pro",
]

SAAS_MODULES = [
    "saas", "saas.config", "saas.auth", "saas.database",
    "saas.models", "saas.email", "saas.webhooks", "saas.billing",
    "saas.routes.auth", "saas.app",
]

# -- Audit Engine ------------------------------------------------------


class AuditColors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


class AuditReport:
    """Collects and presents audit results."""

    def __init__(self, name: str):
        self.name = name
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def ok(self, msg: str) -> None:
        self.passed.append(msg)
        print(f"  {AuditColors.GREEN}[PASS]{AuditColors.RESET} {msg}")

    def fail(self, msg: str) -> None:
        self.failed.append(msg)
        print(f"  {AuditColors.RED}[FAIL]{AuditColors.RESET} {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  {AuditColors.YELLOW}[WARN]{AuditColors.RESET} {msg}")

    def print_summary(self) -> int:
        total = len(self.passed) + len(self.failed)
        print(f"\n{AuditColors.BOLD}{'=' * 60}{AuditColors.RESET}")
        print(
            f"{AuditColors.BOLD}RESULTS:{AuditColors.RESET} "
            f"{AuditColors.GREEN}{len(self.passed)} passed{AuditColors.RESET}, "
            f"{AuditColors.RED}{len(self.failed)} failed{AuditColors.RESET}, "
            f"{AuditColors.YELLOW}{len(self.warnings)} warnings{AuditColors.RESET} "
            f"({total} total)"
        )
        print(f"{AuditColors.BOLD}{'=' * 60}{AuditColors.RESET}")
        return len(self.failed)


# -- Checks ------------------------------------------------------------


def check_env_vars(report: AuditReport) -> None:
    """Verify critical environment variables are set."""
    report.ok("Checking environment variables...")
    for var in REQUIRED_ENV_VARS:
        if os.getenv(var):
            report.ok(f"{var} is set")
        else:
            report.warn(f"{var} is not set (using default)")


def check_imports(report: AuditReport, modules: list[str], label: str) -> None:
    """Verify module imports work correctly."""
    report.ok(f"Checking {label}...")
    for module_name in modules:
        try:
            importlib.import_module(module_name)
            report.ok(f"  {module_name}")
        except ImportError as e:
            report.fail(f"  {module_name}: {e}")
        except Exception as e:
            report.warn(f"  {module_name}: {e}")


def check_core_functionality(report: AuditReport) -> None:
    """Verify core functionality works."""
    report.ok("Checking core functionality...")

    try:
        from ansiq.orchestration.dag import DAG, DAGNode
        d = DAG("audit_test")
        d.add_node(DAGNode(id="a", name="A"))
        d.add_node(DAGNode(id="b", name="B", deps=["a"]))
        viz = d.visualize()
        assert "DAG:" in viz
        report.ok("  DAG creation & visualization works")
    except Exception as e:
        report.fail(f"  DAG test failed: {e}")

    try:
        from ansiq.swarm.consensus import ConsensusEngine
        from ansiq.swarm.intelligence import AgentOpinion, VoteType
        engine = ConsensusEngine()
        opinions = [
            AgentOpinion(agent_name="Alice", agent_role="Engineer",
                         vote=VoteType.AGREE, confidence=0.9),
            AgentOpinion(agent_name="Bob", agent_role="Analyst",
                         vote=VoteType.DISAGREE, confidence=0.5),
        ]
        winner, confidence, _ = engine.resolve(opinions)
        assert winner is not None and confidence > 0
        report.ok("  Consensus engine resolves votes")
    except Exception as e:
        report.fail(f"  Consensus test failed: {e}")

    try:
        from ansiq.llm.router import ModelRouter
        router = ModelRouter()
        result = router.route("Write Python code")
        assert result.selected_model is not None
        report.ok("  Model router selects models")
    except Exception as e:
        report.fail(f"  Router test failed: {e}")

    try:
        from ansiq.tools.discover import list_discovered_tools
        tools = list_discovered_tools()
        assert isinstance(tools, list)
        report.ok(f"  Tool discovery works ({len(tools)} tools)")
    except Exception as e:
        report.fail(f"  Tool discovery test failed: {e}")

    try:
        from ansiq.sandbox.policy import SandboxPolicy
        p = SandboxPolicy()
        allowed, _ = p.validate_command("python --version")
        assert allowed
        report.ok("  Sandbox policy validates commands")
    except Exception as e:
        report.fail(f"  Sandbox policy test failed: {e}")

    try:
        from ansiq.analytics.cost_tracker import CostTracker
        t = CostTracker()
        rec = t.record(agent_name="audit_agent", model="gpt-4o",
                       prompt_tokens=100, completion_tokens=50)
        assert rec is not None
        report.ok("  Cost tracker records usage")
    except Exception as e:
        report.fail(f"  Cost tracker test failed: {e}")


def check_saas_functionality(report: AuditReport) -> None:
    """Verify SaaS module functionality."""
    report.ok("Checking SaaS functionality...")

    try:
        from saas.config import config
        assert config.environment in ("development", "staging", "production")
        report.ok(f"  SaaS config: environment={config.environment}")
    except Exception as e:
        report.fail(f"  SaaS config test failed: {e}")

    try:
        from saas.auth import hash_password, verify_password
        h = hash_password("test123")
        assert verify_password("test123", h) is True
        assert verify_password("wrong", h) is False
        report.ok("  Password hashing & verification works")
    except Exception as e:
        report.fail(f"  Password test failed: {e}")

    try:
        from saas.webhooks import sign_payload
        sig = sign_payload(b'{"test": true}', "secret123")
        assert len(sig) == 64 and isinstance(sig, str)
        report.ok("  Webhook signature (HMAC-SHA256) works")
    except Exception as e:
        report.fail(f"  Webhook test failed: {e}")

    try:
        from saas.email import EmailMessage
        msg = EmailMessage(to="test@test.com", subject="Test",
                           html_body="<p>Hi</p>", text_body="Hi")
        assert msg.to == "test@test.com"
        report.ok("  Email message model works")
    except Exception as e:
        report.fail(f"  Email test failed: {e}")

    try:
        from saas.billing import billing_service
        assert billing_service is not None
        report.ok("  Billing service initialized")
    except Exception as e:
        report.fail(f"  Billing test failed: {e}")

    try:
        from saas.routes.auth import router
        assert router is not None
        report.ok("  SaaS auth routes registered")
    except Exception as e:
        report.fail(f"  Routes test failed: {e}")


def check_auth_models(report: AuditReport) -> None:
    """Verify AnsiQ auth models work."""
    report.ok("Checking auth models...")
    try:
        from ansiq.auth.models import Permission, Session, User
        user = User(email="audit@test.com", username="auditor")
        user.set_password("secure123")
        assert user.verify_password("secure123") is True
        assert user.verify_password("wrong") is False
        assert user.has_permission(Permission.AGENT_READ)
        session = Session(user_id=user.id, expires_at=9999999999)
        assert session.is_valid is True
        report.ok("  User/Session models work correctly")
    except Exception as e:
        report.fail(f"  Auth models test failed: {e}")


def check_rbac(report: AuditReport) -> None:
    """Verify RBAC manager works."""
    report.ok("Checking RBAC manager...")
    try:
        from ansiq.auth.models import Role
        from ansiq.auth.rbac import RBACManager
        with tempfile.TemporaryDirectory() as tmp:
            rbac = RBACManager(storage_path=tmp)
            rbac.create_user(email="rbac@test.com", password="test123",
                             role=Role.ADMIN)
            session = rbac.authenticate(email="rbac@test.com", password="test123")
            assert session is not None and session.is_valid
            bad = rbac.authenticate(email="rbac@test.com", password="wrong")
            assert bad is None
            report.ok("  RBAC: creation, auth, and validation work")
    except Exception as e:
        report.fail(f"  RBAC test failed: {e}")


def check_plugins(report: AuditReport) -> None:
    """Verify plugin system works."""
    report.ok("Checking plugin system...")
    try:
        from ansiq.plugins.manager import PluginManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = PluginManager(config_path=tmp)
            assert mgr.list_plugins() is not None
            report.ok("  Plugin manager: list_plugins() OK")
    except Exception as e:
        report.fail(f"  Plugin system test failed: {e}")
    try:
        from ansiq.plugins.base import PluginCapability, PluginInfo
        pi = PluginInfo(name="test-plugin", version="1.0.0",
                        capabilities=[PluginCapability.TOOL])
        assert pi.name == "test-plugin"
        report.ok("  PluginInfo model works")
    except Exception as e:
        report.fail(f"  PluginInfo test failed: {e}")


def check_api_tenant(report: AuditReport) -> None:
    """Verify multi-tenant API works."""
    report.ok("Checking multi-tenant API...")
    try:
        from ansiq.api.tenant import TenantManager

        with tempfile.TemporaryDirectory() as tmp:
            mgr = TenantManager(storage_path=tmp)
            org = mgr.create_organization(name="AuditCorp", owner_id="audit_owner")
            assert org is not None and org.name == "AuditCorp"
            ws_list = mgr.list_workspaces()
            assert ws_list is not None
            report.ok("  Tenant: organization creation works")
    except Exception as e:
        report.fail(f"  Tenant test failed: {e}")
    try:
        from ansiq.api.keys import APIKeyStore
        with tempfile.TemporaryDirectory() as tmp:
            store = APIKeyStore(storage_path=tmp)
            raw, key_obj = store.generate_key(workspace_id="ws_audit", name="Audit Key")
            assert raw.startswith("ansiq_")
            assert store.validate(raw) is not None
            report.ok("  API keys: generation & validation")
    except Exception as e:
        report.fail(f"  API keys test failed: {e}")


def check_evaluation(report: AuditReport) -> None:
    """Verify evaluation framework works."""
    report.ok("Checking evaluation framework...")
    try:
        from ansiq.evaluation.metrics import QualityMetrics
        qm = QualityMetrics()
        scores = qm.evaluate(output="AnsiQ audit system is working correctly.",
                             expected_keywords=["audit", "system", "working"])
        assert 0 <= scores["overall_score"] <= 1
        report.ok(f"  QualityMetrics: score={scores['overall_score']:.2f}")
    except Exception as e:
        report.fail(f"  QualityMetrics test failed: {e}")
    try:
        from ansiq.evaluation.ab_test import VariantResult
        vr = VariantResult(name="Variant A", avg_score=0.9)
        assert vr.avg_score == 0.9
        report.ok("  AB testing: VariantResult model works")
    except Exception as e:
        report.fail(f"  AB test failed: {e}")


def check_audit_log(report: AuditReport) -> None:
    """Verify audit logging works."""
    report.ok("Checking audit log...")
    try:
        from ansiq.auth.audit import AuditLog, EventType
        with tempfile.TemporaryDirectory() as tmp:
            audit = AuditLog(storage_path=tmp)
            event = audit.log(event_type=EventType.LOGIN_SUCCESS,
                              actor_id="usr_audit", description="Audit test login")
            assert event is not None
            results = audit.search(event_type=EventType.LOGIN_SUCCESS)
            assert len(results) == 1
            report.ok("  AuditLog: event recording & search")
    except Exception as e:
        report.fail(f"  AuditLog test failed: {e}")


# -- Main --------------------------------------------------------------


def main() -> int:
    """Run the full audit and return exit code (0 = all OK)."""
    print(f"\n{'=' * 60}")
    print("   AnsiQ - Production Audit Checker")
    print(f"{'=' * 60}")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Path:   {Path(__file__).parent.resolve()}")

    report = AuditReport("AnsiQ Audit")

    check_env_vars(report)
    check_imports(report, CORE_MODULES, "Core Module Imports")
    check_imports(report, SAAS_MODULES, "SaaS Module Imports")
    check_core_functionality(report)
    check_saas_functionality(report)
    check_auth_models(report)
    check_rbac(report)
    check_plugins(report)
    check_api_tenant(report)
    check_evaluation(report)
    check_audit_log(report)

    failed = report.print_summary()
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
