# SECURITY_REVIEW.md

## Secret scan (local static pass)

- `.env*` patterns: **not found** in top-level project scan.
- Common secret-like file patterns (`*.pem`, `*.key`, `*token*`, `*secret*`): **not found in top-level scan**.
- Credential-bearing files discovered later should be moved to `.env.example`/private secrets store and removed before publish.

## Remediations

- Add `.env.example` with non-sensitive placeholders.
- Keep `.venv`, `.pytest_cache`, `.ruff_cache` out of publish-ready directories.
- Block `.pdf`, large `.json` and source API payloads where rights are unknown.
