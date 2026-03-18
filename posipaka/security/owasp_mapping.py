"""OWASP Top 10 (2021) mapping до контролів Posipaka."""

from __future__ import annotations

OWASP_TOP10_MAPPING: dict[str, dict[str, str]] = {
    "A01:2021 — Broken Access Control": {
        "risk": "Несанкціонований доступ до функцій/даних",
        "controls": (
            "AuthMiddleware на всі маршрути; "
            "PermissionChecker + PermissionProfile; "
            "FilesystemPolicy (ALWAYS_DENIED/REQUIRES_APPROVAL); "
            "WebhookRateLimiter (120 req/min per IP); "
            "Approval gates для деструктивних дій"
        ),
        "modules": (
            "web/auth.py, core/permission_checker.py, "
            "security/filesystem_policy.py, web/middleware.py"
        ),
    },
    "A02:2021 — Cryptographic Failures": {
        "risk": "Витік секретів, слабке шифрування",
        "controls": (
            "SecretsManager (Fernet AES-128); "
            "bcrypt для паролів; "
            "secrets.token_urlsafe для session tokens; "
            "secrets.compare_digest для timing-safe порівнянь; "
            "HSTS header для HTTPS"
        ),
        "modules": "security/secrets.py, web/auth.py, web/security_headers.py",
    },
    "A03:2021 — Injection": {
        "risk": "Prompt injection, command injection, path traversal",
        "controls": (
            "InjectionDetector (EN/UA/RU patterns + homoglyph normalization); "
            "sanitize_external_content() для email/web; "
            "ShellSandbox (destructive pattern detection); "
            "validate_path() для path traversal; "
            "validate_url() для SSRF"
        ),
        "modules": (
            "security/injection.py, security/sandbox.py, "
            "security/path_traversal.py, security/ssrf.py"
        ),
    },
    "A04:2021 — Insecure Design": {
        "risk": "Архітектурні вразливості",
        "controls": (
            "tarfile.extractall(filter='data') для backup restore; "
            "SkillSandbox.validate_skill_source() для workspace skills; "
            "MAX_INPUT_LENGTH=8000 перед Agent.handle_message(); "
            "MAX_TOOL_LOOPS=10 для agentic loop"
        ),
        "modules": "utils/backup.py, security/skill_sandbox.py, core/agent.py",
    },
    "A05:2021 — Security Misconfiguration": {
        "risk": "Дефолтні конфігурації, зайві функції",
        "controls": (
            "SecurityHeadersMiddleware (CSP, X-Frame-Options, etc.); "
            "CORS з explicit origin list; "
            ".dockerignore виключає AI-артефакти; "
            "Docker image scanning (Trivy)"
        ),
        "modules": "web/security_headers.py, web/app.py, .dockerignore",
    },
    "A06:2021 — Vulnerable Components": {
        "risk": "Вразливі залежності",
        "controls": (
            "Dependency upper bounds в pyproject.toml; "
            "SBOM generation (CycloneDX); "
            "Trivy scanning в CI; "
            "Dependabot alerts"
        ),
        "modules": (
            "pyproject.toml, .github/workflows/sbom.yml, "
            ".github/workflows/docker-security.yml"
        ),
    },
    "A07:2021 — Identification and Authentication Failures": {
        "risk": "Обхід автентифікації",
        "controls": (
            "Brute-force lockout (5 спроб → 5 хв); "
            "Session fixation prevention (invalidate old session on login); "
            "MAX_CONCURRENT_SESSIONS=3 per IP; "
            "8h session TTL; "
            "CSRF tokens для POST/PUT/DELETE"
        ),
        "modules": "web/auth.py",
    },
    "A08:2021 — Software and Data Integrity Failures": {
        "risk": "Неверифікований код, tampered data",
        "controls": (
            "Hash-chained audit log (SHA-256); "
            "SBOM generation; "
            "SkillSandbox validation; "
            "skill.lock для verified skills"
        ),
        "modules": "security/audit.py, security/skill_sandbox.py",
    },
    "A09:2021 — Security Logging and Monitoring Failures": {
        "risk": "Відсутність логування security подій",
        "controls": (
            "AuditLogger для КОЖНОЇ дії (hash-chained); "
            "Structured JSON logging (loguru); "
            "MetricsRegistry (Prometheus-compatible); "
            "SLOMonitor + DriftDetector"
        ),
        "modules": (
            "security/audit.py, core/json_logging.py, "
            "core/observability.py, core/slo_monitor.py"
        ),
    },
    "A10:2021 — Server-Side Request Forgery (SSRF)": {
        "risk": "Доступ до внутрішніх сервісів через URL",
        "controls": (
            "validate_url() блокує private/loopback/link-local IP; "
            "URLValidator для web_fetch/web_screenshot; "
            "DNS rebinding protection"
        ),
        "modules": "security/ssrf.py, integrations/browser/tools.py",
    },
}


def get_owasp_report() -> str:
    """Повернути текстовий звіт OWASP Top 10 mapping."""
    lines = ["OWASP Top 10 (2021) — Posipaka Security Controls Mapping", "=" * 60]
    for category, info in OWASP_TOP10_MAPPING.items():
        lines.append(f"\n{category}")
        lines.append(f"  Ризик: {info['risk']}")
        lines.append(f"  Контролі: {info['controls']}")
        lines.append(f"  Модулі: {info['modules']}")
    return "\n".join(lines)
