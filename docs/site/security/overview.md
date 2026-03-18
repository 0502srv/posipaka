# Безпека

## Принцип

```
БЕЗПЕКА > ПРОСТОТА > ФУНКЦІОНАЛЬНІСТЬ
```

Posipaka має доступ до email, shell, файлів — тому безпека є фундаментом.

## Захисні шари

### 1. Injection Detection
Мультимовне виявлення prompt injection (EN/UA/RU):
- Pattern matching (100+ шаблонів)
- Homoglyph normalization
- Structural analysis
- Threshold: 0.7

### 2. Shell Sandbox
Блокує небезпечні команди:
- `rm -rf /`, fork bombs, `shutdown`
- `curl | bash`, `wget | sh`
- Timeout enforcement

### 3. SSRF Protection
Блокує запити до внутрішніх мереж:
- 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- localhost, 169.254.169.254 (cloud metadata)
- Порти: SSH, MySQL, PostgreSQL, Redis

### 4. Path Traversal Protection
Блокує доступ до системних файлів:
- /etc/shadow, /etc/passwd
- `..' traversal
- Symlink resolution

### 5. Audit Log
Hash-chained JSONL (SHA-256):
- Кожна дія логується
- Tamper detection
- CSV export для compliance

### 6. Approval Gates
Деструктивні дії потребують підтвердження:
- send_email, delete_file
- shell rm, github_commit
- Inline кнопки в Telegram

### 7. Cost Guard
Контроль витрат:
- Daily budget (default: $5)
- Per-request limit
- Per-session limit

### 8. Skill Sandbox
AST-аналіз workspace skills:
- Import whitelist
- Blocked: eval, exec, os, subprocess
- Integrity verification (skill.lock)

## OWASP Top 10 Coverage

| OWASP | Захист |
|-------|--------|
| A01 Broken Access Control | AuthMiddleware, Permissions |
| A02 Crypto Failures | cryptography, bcrypt |
| A03 Injection | InjectionDetector, ShellSandbox |
| A04 Insecure Design | Security-first architecture |
| A05 Security Misconfiguration | Sensible defaults |
| A06 Vulnerable Components | pip-audit, Trivy, dependabot |
| A07 Auth Failures | Brute-force protection, session TTL |
| A08 Software Integrity | SBOM, signed commits |
| A09 Logging Failures | Hash-chained audit, structured logging |
| A10 SSRF | SSRFProtector |
