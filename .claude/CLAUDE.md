# Project-specific Claude Instructions

## Rules

Project context is in `.claude/rules/`:
- `architecture.md` — Project overview, directory tree, design patterns, code style
- `api-reference.md` — Endpoints, config env vars (auto-loaded for `api/` files)
- `schema.md` — SurrealDB schema (auto-loaded for `api/` files)
- `dev-commands.md` — Dev workflow, testing, linting, scripts
- `versioning.md` — Semantic versioning policy and Makefile bump commands
- `migrations.md` — Migration system (auto-loaded for migration files)
- `deployment.md` — Ansible deploy, version gate, Docker Desktop safety rule
- `troubleshooting.md` — Server access, logs, common issues
- `gotchas.md` — Cross-platform issues, container gotchas

Available reusable skills are in `.claude/skills/`.
