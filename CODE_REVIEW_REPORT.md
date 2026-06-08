# AnsiQ — Code Review & Production-Readiness Report

**Date:** 2026-06-06
**Reviewer:** Professional Code Reviewer
**Scope:** Full SaaS stack (FastAPI, SQLAlchemy, Stripe, Auth, Webhooks, etc.)

---

## TL;DR — VERDICT

| Status | Readiness |
|---|---|
| 🟡 **NOT READY for production SaaS** | Needs critical fixes |
| ✅ Internal MVP / Beta | OK for limited pilot |
| ✅ Development | Passes 91/91 unit tests |

**The audit script reports 91 passed / 0 failed / 3 warnings, but surface-level tests do not cover security, business logic, or end-to-end flows.** Many critical bugs only show up under real traffic or hostile input.

---

## CRITICAL BUGS (must-fix before any production deploy)

### 🔴 1. Password Hashing Uses Insecure SHA-256
- **File:** `saas/auth.py:26-38` and `ansiq/auth/models.py:217-231`
- **Issue:** `hash_password()` and `set_password()` use `hashlib.sha256(salt + password)`. SHA-256 is a fast hash — vulnerable to GPU/ASIC brute-force (10⁹ guesses/sec on consumer GPUs).
- **Smoking gun:** `saas/config.py:95` defines `bcrypt_rounds: int = 12` but it is **never used anywhere in the codebase**. The config field is dead code.
- **Fix:** Replace with `bcrypt.hashpw` (or `argon2-cffi`). Bcrypt output is 60 chars — `password_hash: String(255)` is fine.
- **Severity:** **CRITICAL** — Any DB leak = instant password recovery.

### 🔴 2. Hardcoded Default JWT Secret
- **File:** `saas/config.py:91`
- **Code:** `jwt_secret: str = os.getenv("ANSIQ_JWT_SECRET", "change-me-in-production-change-me-now-32bytes")`
- **Issue:** If the env var is missing (e.g., container started without `-e ANSIQ_JWT_SECRET=...`), the placeholder is silently used. Same for `secret_key = "change-me"`. There is no startup check that rejects the default in `production`.
- **Exploit:** An attacker who reads the public repo or guesses the literal default can forge JWTs for any user.
- **Fix:** Raise on app start if `config.is_production and "change-me" in config.security.jwt_secret`.

### 🔴 3. API Surface Is Incomplete (~85% Missing)
- **File:** `saas/app.py:140-142` registers **only** the auth router.
- **Total routes exposed: 7** (`/health`, `/ready`, `/version`, `/api/v1/auth/{signup,login,refresh,logout,me,password-reset}`).
- **Missing from `saas/routes/`:** agents, crews, tasks, workspaces, webhooks, billing, api_keys, tenants, memory, knowledge, sandbox, evaluation, analytics.
- **Models exist for all of these (`saas/models.py`) but have zero HTTP routes** → effectively dead code.
- **Severity:** **CRITICAL** — Product is non-functional from a customer perspective.

### 🔴 4. Operator-Precedence Bug in Stripe Update
- **File:** `saas/billing.py:115`
- **Code:**
  ```python
  items_data = getattr(stripe_sub, "items", None) or stripe_sub.get("items") if hasattr(stripe_sub, "get") else getattr(stripe_sub, "items", None)
  ```
- Python parses this as: `(getattr(...) or stripe_sub.get("items")) if hasattr(stripe_sub, "get") else getattr(stripe_sub, "items", None)`
- The intended logic was: `getattr(...) or (stripe_sub.get("items") if hasattr(...) else getattr(...))`
- **Effect:** `update_subscription()` will throw `AttributeError` for dict-like Stripe objects and silently misbehave for object-like ones.
- **Fix:** Use explicit parentheses.

### 🔴 5. Email Verification & Password Reset Are Stubs
- **File:** `saas/routes/auth.py:64, 149`
- **Code:** `await email_service.send_verification_email(user.email, "placeholder-token")` and `"placeholder-reset-token"`.
- **Issue:** No token is generated, no DB record, no endpoint to consume the token. Emails go out with literal `"placeholder-token"` in the URL. Users click the link and get 404.
- **Severity:** **CRITICAL** — Account activation & password recovery flows are completely broken.

### 🔴 6. Stripe Webhook Handlers Will Crash on Unknown Status
- **File:** `saas/billing.py:199`
- **Code:** `db_sub.status = SubscriptionStatus(sub["status"])`
- **Issue:** `SubscriptionStatus(str)` is a `str` Enum — passing an unknown value raises `ValueError`. Stripe adds new statuses over time (e.g., `unpaid`, `paused` was added recently).
- **Effect:** A single unanticipated Stripe event kills the webhook handler. **No `try/except` around the entire handler.**
- **Fix:** Wrap in `try/except` and log; fall back to safe default.

### 🔴 7. Setup Script sed Pattern Doesn't Match `.env.example`
- **File:** `scripts/setup.sh:55-56`
- **Code:**
  ```bash
  sed -i '' "s/change-this-to-a-random-64-char-string/$SECRET_KEY/" .env
  ```
- **`.env.example` actual text:** `generate-a-random-64-char-string-here`
- **Effect:** `setup.sh` claims it generated secrets but silently fails — the user ends up with placeholder secrets in their `.env` and no warning.

### 🔴 8. Webhook Delivery Blocks Request Thread
- **File:** `saas/webhooks.py:67-68`
- **Code:** `await _deliver(...)` inside a `for` loop — sequential, blocking, with `2 ** attempt` second backoffs (2s, 4s, 8s).
- **Effect:** A `POST /agents/run` that triggers 3 webhooks waits up to 14+ seconds if endpoints are slow. The original HTTP request times out. This is a DoS vector — slow webhook endpoints slow the entire API.
- **Fix:** Use `asyncio.create_task()` or, better, a proper queue (Celery / RQ / Arq with Redis).

---

## HIGH-SEVERITY ISSUES

### 🟠 9. No Database Migrations for Production
- `init_db()` only runs in dev (`saas/app.py:31-33`). Uses `Base.metadata.create_all`.
- `alembic/` folder exists but is not wired to the FastAPI lifespan.
- `_TBL_KW = {"extend_existing": True}` in `saas/models.py:28` is a code smell that hides real schema problems.

### 🟠 10. Auth Logging Setup Race
- `saas/app.py:28-30`: `logger.info(...)` is called **before** `setup_logging(...)`. The startup log line uses the default Python logging config, not your JSON handler. First line of every prod log is a plain `INFO:saas.app:Starting...`.

### 🟠 11. RBAC is Not Used by SaaS Routes
- `ansiq/auth/rbac.py` has a full RBAC implementation but `saas/auth.py` uses a much simpler `require_role` factory.
- Two parallel auth systems exist, with the simpler one being used. This is confusing for maintainers and bypasses audit logging in `ansiq.auth.audit.AuditLog`.

### 🟠 12. Models Are Not Tenant-Scoped in Queries
- `saas/routes/auth.py:101` does `select(User).where(User.id == session.user_id)` — does **not** filter by `organization_id`. Combined with `payload["sub"]` being the user id (not org-scoped), a leaked user id from any org can be used.
- A user from org A can refresh tokens for a user from org B if they share an email collision (mitigated by unique email, but the code path is still unsafe).

### 🟠 13. `__import__("sqlalchemy").text("SELECT 1")` in Health
- **File:** `saas/app.py:85`
- `from sqlalchemy import text` at the top of the file would be cleaner. Currently uses dynamic import — anti-pattern, harder to lint, slower.

### 🟠 14. Rate Limiting Is Configured But Never Enforced
- `config.security.rate_limit_per_minute` exists, `nginx.conf` has limit_req zones, but **the FastAPI app has no `slowapi` or equivalent middleware**.
- All enforcement happens at nginx. Behind a load balancer that doesn't preserve client IP, this breaks.

### 🟠 15. `_TBL_KW = {"extend_existing": True}` in All Models
- This tells SQLAlchemy to ignore "table already defined" errors. It is hiding potential schema collisions in tests, and may silently drop constraints.

### 🟠 16. Webhook Secret Stored in Plaintext
- `WebhookEndpoint.secret: Mapped[str]` is plaintext in DB. If DB is leaked, attackers can forge webhook signatures to customer's endpoints.
- Use KMS / envelope encryption.

### 🟠 17. User Counters / Quotas Not Enforced
- `Organization.max_users`, `max_workspaces`, `max_tasks_per_month` exist as columns but **no code checks them** before creating users, workspaces, or recording usage. Plan limits are not enforced.

### 🟠 18. No Database Indexes on Critical Columns
- `Session.refresh_token_hash` is `unique=True` so it gets an index — good.
- But `AuditLog.user_id`, `Invoice.stripe_invoice_id` lookups, `ApiKey.key_hash` — need composite indexes for production query patterns.

### 🟠 19. Email `from cors_origins[0]` Is a Bug
- `saas/email.py:48, 63`: `url = f"{config.security.cors_origins[0]}/verify-email?token={token}"`
- If `cors_origins == ["*"]` (default), the URL becomes `*/verify-email?token=...` — a literal asterisk in the link, not a valid URL.
- Should use a dedicated `ANSIQ_APP_URL` env var.

### 🟠 20. Password Reset & Email Verify Don't Exist in Model
- `Session` model has refresh tokens only. There is **no `EmailVerificationToken` or `PasswordResetToken` table**. The stubs at `routes/auth.py:64, 149` cannot be completed without adding models.

---

## MEDIUM-SEVERITY ISSUES

### 🟡 21. CORS `allow_methods=["*"]` and `allow_headers=["*"]`
- Overly permissive. Whitelist `["GET", "POST", "PUT", "DELETE", "OPTIONS"]` and `["Authorization", "Content-Type", "X-Requested-With"]`.

### 🟡 22. `bcrypt_rounds` Configured But Never Read
- `saas/config.py:95`. Dead config. Misleading.

### 🟡 23. UUID Stored as `String(36)` Instead of Native UUID
- `saas/database.py:34-36` uses `String(36)`. PostgreSQL has a native `UUID` type that uses 16 bytes vs 36, and supports `uuid_generate_v4()` server-side. Inefficient.

### 🟡 24. `User.password_hash: String(255)` is OK for bcrypt but Tight
- Argon2 PHC string is ~95 chars. Still fits, but consider `String(512)` for future hash agility.

### 🟡 25. No `aiosmtplib` Listed in `pyproject.toml` Dependencies
- `saas/email.py:92` imports `aiosmtplib`, but `pyproject.toml` only lists `sendgrid` (transitively) and `boto3` is implicit. The SMTP path will `ImportError` on a fresh install.

### 🟡 26. `from saas.auth import hash_password` Used in Route
- `saas/routes/auth.py:15` imports `hash_password` but it's never used in `auth.py` route file. Dead import.

### 🟡 27. `email_service.send_*` Methods Are Async But Block in Routes
- `routes/auth.py:64, 149` `await` the email call. If SMTP is slow, the signup/login request is slow. Should be `asyncio.create_task()` (fire-and-forget) or pushed to a queue.

### 🟡 28. `version` Endpoint Duplicated
- `app.version = "0.1.0"` and the `/version` endpoint also hardcode `0.1.0`. Should use `from ansiq import __version__` (already defined in `ansiq/__init__.py:9`).

### 🟡 29. No Request-ID / Correlation-ID
- Logs cannot be correlated across services. Add a middleware that injects `X-Request-ID` into both `request.state` and the log context.

### 🟡 30. Unbounded `AuditLog._save` Writes Full JSON on Every Event
- `ansiq/auth/audit.py:266-274` writes the entire `audit.json` on every `log()` call. With high event rate, this is O(n) per write. Use append-only or batching.

### 🟡 31. `test_all_modules.py` Does Not Use `pytest` Properly
- It is a custom test runner (`_run_test` function) inside `if __name__ == "__main__"`. `pytest` is in dev deps but the file won't be discovered by pytest (no `test_` function names with `assert` and no class). The "91 passed" includes module imports only.

### 🟡 32. `Dockerfile` Production Stage Has HEALTHCHECK Using `curl`
- `Dockerfile:48-49` uses `curl` against the local app, but `curl` is only installed in the `base` stage. Make sure user `ansiq` has access. (The build doesn't break but the container health is `unhealthy`.)

### 🟡 33. `daemon` User Inside Container Runs as Root Initially
- `Dockerfile:42-44` creates user correctly, but `pip install` in the `base` stage runs as root (acceptable, build stage). The `production` stage then `USER ansiq` — OK. But `gunicorn` is installed in the base stage and never used in CMD (CMD uses uvicorn). Dead dep.

### 🟡 34. `app.py` Uses `__import__("sqlalchemy")` for `text("SELECT 1")`
- Hard-coded dynamic import. Should be: `from sqlalchemy import text` at the top.

### 🟡 35. `python-decouple` Not Used Despite Complex Env Handling
- `os.getenv(...)` repeated 30+ times. Use `pydantic-settings` (already a transitive dep) for typed config.

### 🟡 36. Soft-Delete / GDPR Right-to-Erasure Not Implemented
- `User` model has no `deleted_at` column. The `AuditLog` table is described as "immutable" but `clear()` exists. No way to honor GDPR Article 17 ("right to be forgotten") properly.

### 🟡 37. No Multi-Factor Authentication
- `User.mfa_enabled: bool` exists in `models.py` and `audit/models.py` but **no TOTP/SMS implementation** anywhere. Field is dead.

### 🟡 38. `ApiKey.allowed_ips: Mapped[Optional[list]]` Stored as JSON
- JSON column for IP allow-listing. Hard to index, hard to query "is this IP allowed?". Should be a separate `ApiKeyAllowedIp` table.

### 🟡 39. No HTTPS Enforcement / HSTS
- nginx does it. But the FastAPI app does not reject plain HTTP if exposed directly. Not a bug if always behind nginx.

### 🟡 40. `__init__.py` Files Have Hardcoded Author / Version
- `ansiq/__init__.py:9` `__version__ = "0.1.0"`. If you bump to 0.2.0, you have to remember to update many places.

### 🟡 41. `eval()` and `pickle` Not Used Anywhere (good) — but `yaml.load` (not `safe_load`) should be checked
- Did not spot any `yaml.load` without `Loader=SafeLoader`. ✅

### 🟡 42. `extra_metadata: Mapped[...] = mapped_column("meta", JSON, ...)`
- `"meta"` is a reserved word in some SQL dialects (PostgreSQL allows it, MySQL doesn't). Rename to `meta_data` or `subscription_metadata`.

### 🟡 43. No API Versioning Beyond `/api/v1`
- `saas/app.py` only mounts v1. There is no router for `/api/v2`. No deprecation strategy. Acceptable for v0.1.0.

### 🟡 44. Missing Prometheus `/metrics` Endpoint
- `monitoring/prometheus.yml:17` scrapes `/metrics` from `app:8000`, but the FastAPI app does **not** expose a `/metrics` route. `prometheus_client` is in deps but not wired.

### 🟡 45. No Sentry Source Maps / Profiling
- `sentry-sdk` is initialized but `profiles_sample_rate` and `traces_sample_rate` are not pulled from env (default 0.1). For a production SaaS, you typically want 0.05–0.2 depending on traffic.

### 🟡 46. `dashboard` Docker Service Has No Healthcheck for the Streamlit App
- `Dockerfile:61-62` defines one but Streamlit's `/healthz` is not standard. May always return 503.

### 🟡 47. `_TBL_KW` is Dict-of-One-Key Shared Across All Models
- If you ever want to override per-model table args, you must merge manually.

### 🟡 48. No CSRF Tokens for Cookie-Based Auth
- All routes use `Authorization: Bearer ...` so CSRF is technically not exploitable. ✅ But if you ever add cookie auth (Streamlit dashboard likely does), no protection.

### 🟡 49. Streamlit Dashboard is Configured With `--server.enableXsrfProtection=false`
- **XSRF disabled by default in the Docker dashboard.** If the dashboard ever sets cookies, this is a CSRF risk.

### 🟡 50. No Backups, DR Plan, or Runbook in the Repo
- `scripts/deploy.sh` exists but is not in scope of this review.

---

## WHAT IS GOOD ✅

- ✅ Tests pass (91/91) — surface-level only, but no syntax/import errors
- ✅ SQLAlchemy 2.0 with `Mapped` and `mapped_column` (modern)
- ✅ Proper `asyncpg` driver + connection pool
- ✅ Pydantic models for API schemas
- ✅ Structured JSON logging in `ansiq/saas/logging.py`
- ✅ Optional Sentry integration (DSN-gated)
- ✅ nginx with HTTPS, HSTS, rate limiting, security headers
- ✅ Multi-stage Dockerfile (small prod image, non-root user)
- ✅ docker-compose with Postgres + Redis + Nginx + (optional) Prometheus/Grafana
- ✅ Health and readiness probes separated
- ✅ Webhook delivery with HMAC-SHA256 signing and retries
- ✅ RBAC implementation exists (`ansiq/auth/rbac.py`) — even if not used by SaaS routes
- ✅ Audit log model with composite indexes
- ✅ Stripe webhook signature verification
- ✅ Alembic folder present (just not wired to lifespan)

---

## PRIORITIZED FIX ROADMAP

### Phase 1 — STOP THE BLEEDING (1–2 days, must-fix before any user signups)
1. Replace SHA-256 password hashing with **bcrypt** (or argon2) in `saas/auth.py` AND `ansiq/auth/models.py`.
2. Add production-mode validation that rejects default `jwt_secret` and `secret_key`.
3. Fix the operator-precedence bug in `saas/billing.py:115`.
4. Wrap Stripe webhook handlers in `try/except`.
5. Fix `scripts/setup.sh` sed pattern.
6. Move webhook delivery off the request thread (background tasks or queue).

### Phase 2 — MAKE IT A PRODUCT (1–2 weeks)
7. Implement `EmailVerificationToken` and `PasswordResetToken` models + endpoints.
8. Build the missing API routes: agents, crews, tasks, workspaces, webhooks, billing, api_keys, tenants, memory, knowledge, sandbox, evaluation, analytics. (At minimum: a `routes/agents.py` skeleton that actually works.)
9. Wire `alembic upgrade head` into deployment; remove `_TBL_KW["extend_existing"]`.
10. Add Prometheus `/metrics` endpoint.
11. Enforce plan limits (`max_users`, `max_tasks_per_month`).
12. Add rate limiting inside FastAPI (slowapi).
13. Use `ANSIQ_APP_URL` for email links, not `cors_origins[0]`.
14. Add request-ID middleware for log correlation.
15. Add `aiosmtplib` to `pyproject.toml` deps.

### Phase 3 — HARDEN FOR PRODUCTION (2–4 weeks)
16. Add MFA / TOTP.
17. Encrypt webhook secrets at rest.
18. Add GDPR data export & soft-delete.
19. Add backup/restore runbook.
20. Add a real test suite (pytest, integration tests, security tests).
21. Add CI that runs `ruff`, `mypy --strict`, `pytest`, and a security scan (`bandit`, `pip-audit`).
22. Move auth to RBAC; delete the simpler `require_role` factory.
23. Switch to `pydantic-settings` for typed config.
24. Add error budget / SLOs.

---

## BOTTOM LINE

> **Is it ready to use?**
> Yes — for an internal demo, single-tenant pilot, or open-source framework showcase. The 91/91 audit pass is real for what it tests.

> **Is it ready for production SaaS?**
> **No.** Eight critical bugs must be fixed first, ~85% of the advertised product has no HTTP surface, password hashing is broken, and password reset / email verification are stubs. Shipping this to paying customers today would result in:
> - Compromised passwords within hours of any DB leak
> - Inability to sign up (placeholder tokens break the flow)
> - Stripe webhooks crashing on unknown statuses
> - API timeouts when customer webhooks are slow
> - Customer support nightmare from a 7-route API when the marketing site promises multi-agent orchestration

> **Estimated effort to MVP-launch:** **2–3 weeks of focused engineering** for Phase 1 + Phase 2.
> **Estimated effort to enterprise-grade SaaS:** **6–10 weeks** including all of Phase 3.

---

**Reviewer's Note:** The codebase is well-structured, well-commented, and uses modern async Python patterns. The author clearly understands FastAPI, SQLAlchemy 2.0, and SaaS architecture. The gaps are in *completion* (missing endpoints, stubbed flows) and *security hardening* (bcrypt, secret validation) — not in fundamental design. With the Phase 1 fixes, this is a credible open-source product. With Phase 2+3, it's a credible SaaS.


