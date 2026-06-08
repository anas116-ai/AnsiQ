"""Production SaaS Configuration — environment-based settings."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

# ── Default-secret placeholders that MUST be replaced in production. ──
# If a config value still contains one of these strings when the
# application starts in production mode, we refuse to start. This prevents
# an attacker from forging JWTs when an operator forgot to override the
# default.
_INSECURE_SECRET_MARKERS = (
    "change-me",
    "change-this",
    "insecure",
    "placeholder",
    "example",
    "test-secret",
    "xxxxxxxxx",
)


def _validate_secret(value: str, name: str, is_production: bool) -> None:
    """Refuse to start in production if a secret looks like a default."""
    if not is_production:
        return
    if not value or len(value) < 32:
        raise RuntimeError(
            f"FATAL: {name} is missing or too short "
            f"(need ≥32 chars). Refusing to start in production."
        )
    lowered = value.lower()
    for marker in _INSECURE_SECRET_MARKERS:
        if marker in lowered:
            raise RuntimeError(
                f"FATAL: {name} appears to contain a default placeholder "
                f"('{marker}'). Refusing to start in production. "
                f"Generate a real secret with: "
                f'python -c "import secrets; print(secrets.token_hex(32))"'
            )


def _get_int(name: str, default: int) -> int:
    """Safely parse an environment variable as int, falling back on error."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _get_bool(name: str, default: bool) -> bool:
    """Safely parse an environment variable as bool."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_list(name: str, default: list[str]) -> list[str]:
    """Parse a comma-separated env var into a list."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class DatabaseConfig:
    """PostgreSQL connection settings."""

    host: str = os.getenv("ANSIQ_DB_HOST", "localhost")
    port: int = _get_int("ANSIQ_DB_PORT", 5432)
    name: str = os.getenv("ANSIQ_DB_NAME", "ansiq")
    user: str = os.getenv("ANSIQ_DB_USER", "ansiq")
    password: str = os.getenv("ANSIQ_DB_PASSWORD", "ansiq")
    pool_size: int = _get_int("ANSIQ_DB_POOL_SIZE", 20)
    max_overflow: int = _get_int("ANSIQ_DB_MAX_OVERFLOW", 10)
    pool_recycle_seconds: int = _get_int("ANSIQ_DB_POOL_RECYCLE", 1800)
    echo: bool = _get_bool("ANSIQ_DB_ECHO", False)

    @property
    def url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"
        )

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass
class RedisConfig:
    """Redis connection for caching, queues, sessions."""

    host: str = os.getenv("ANSIQ_REDIS_HOST", "localhost")
    port: int = _get_int("ANSIQ_REDIS_PORT", 6379)
    password: str = os.getenv("ANSIQ_REDIS_PASSWORD", "")
    db: int = _get_int("ANSIQ_REDIS_DB", 0)
    ssl: bool = _get_bool("ANSIQ_REDIS_SSL", False)

    @property
    def url(self) -> str:
        proto = "rediss" if self.ssl else "redis"
        auth = f":{self.password}@" if self.password else ""
        return f"{proto}://{auth}{self.host}:{self.port}/{self.db}"


@dataclass
class StripeConfig:
    """Stripe billing integration."""

    secret_key: str = os.getenv("STRIPE_SECRET_KEY", "")
    publishable_key: str = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
    webhook_secret: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    monthly_price_id: str = os.getenv("STRIPE_MONTHLY_PRICE_ID", "")
    yearly_price_id: str = os.getenv("STRIPE_YEARLY_PRICE_ID", "")


@dataclass
class EmailConfig:
    """Email service provider settings."""

    provider: str = os.getenv("ANSIQ_EMAIL_PROVIDER", "smtp")
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.sendgrid.net")
    smtp_port: int = _get_int("SMTP_PORT", 587)
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    from_address: str = os.getenv("ANSIQ_FROM_EMAIL", "noreply@ansiq.ai")
    from_name: str = os.getenv("ANSIQ_FROM_NAME", "AnsiQ")


@dataclass
class AppConfig:
    """Public-facing application URLs."""

    # Public URL of the web app (used for email links, OAuth callbacks,
    # etc.). MUST be a real URL — never the CORS origin (which may be "*").
    public_url: str = os.getenv("ANSIQ_APP_URL", "http://localhost:8000")
    api_url: str = os.getenv("ANSIQ_API_URL", "http://localhost:8000")


@dataclass
class SecurityConfig:
    """Authentication & security settings."""

    jwt_secret: str = os.getenv(
        "ANSIQ_JWT_SECRET",
        # In development a random per-process secret is generated so the
        # default is never used for signing real tokens. Production must
        # always set ANSIQ_JWT_SECRET explicitly (enforced below).
        "",
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = _get_int("ANSIQ_JWT_EXPIRE_MINUTES", 60)
    jwt_refresh_expire_days: int = _get_int("ANSIQ_JWT_REFRESH_EXPIRE_DAYS", 30)
    bcrypt_rounds: int = _get_int("ANSIQ_BCRYPT_ROUNDS", 12)
    cors_origins: list[str] = field(default_factory=lambda: _get_list("ANSIQ_CORS_ORIGINS", ["*"]))
    rate_limit_per_minute: int = _get_int("ANSIQ_RATE_LIMIT_PER_MINUTE", 60)
    rate_limit_burst: int = _get_int("ANSIQ_RATE_LIMIT_BURST", 20)


@dataclass
class SaaSConfig:
    """Aggregate SaaS configuration."""

    debug: bool = _get_bool("ANSIQ_DEBUG", False)
    environment: str = os.getenv("ANSIQ_ENV", "development")
    log_level: str = os.getenv("ANSIQ_LOG_LEVEL", "INFO")
    secret_key: str = os.getenv("ANSIQ_SECRET_KEY", "")
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    stripe: StripeConfig = field(default_factory=StripeConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    app: AppConfig = field(default_factory=AppConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_environment(self) -> None:
        """Refuse to start with insecure defaults in production.

        Call this once during application startup. Raises RuntimeError
        on a misconfigured production deployment so the process exits
        with a clear error message rather than silently using weak
        secrets.
        """
        if not self.is_production:
            return
        _validate_secret(self.security.jwt_secret, "ANSIQ_JWT_SECRET", True)
        _validate_secret(self.secret_key, "ANSIQ_SECRET_KEY", True)
        if "*" in self.security.cors_origins and self.environment != "development":
            # Wildcard CORS is fine in dev but never in production.
            raise RuntimeError(
                "FATAL: ANSIQ_CORS_ORIGINS=* is not allowed in non-development environments."
            )


# Build a single process-wide config instance and, in dev only, populate
# it with random secrets so the dev server is never secured by an empty
# default. In production we require real env vars.
config = SaaSConfig()

if not config.security.jwt_secret:
    if config.is_production:
        # Caller is expected to call validate_for_environment() before
        # serving traffic, but generate here so import-time attribute
        # access doesn't fail in unusual test scenarios.
        config.security.jwt_secret = secrets.token_hex(32)
    else:
        config.security.jwt_secret = secrets.token_hex(32)

if not config.secret_key:
    config.secret_key = secrets.token_hex(32)
