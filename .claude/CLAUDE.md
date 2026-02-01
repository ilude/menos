# Project-specific Claude Instructions

## Deployment

### Docker Desktop Required

**If Docker Desktop is not running and a task requires it (deployment, Ansible, container operations):**

1. STOP immediately
2. Ask the user to start Docker Desktop
3. Do NOT attempt workarounds (direct file operations, rm -rf, manual scp, etc.)

Workarounds to deployment tooling can lead to dangerous operations on production servers. Always use the proper deployment pipeline.

### Deployment Commands

Use Ansible for deployment:
```bash
cd infra/ansible
docker compose run --rm ansible ansible-playbook -i inventory/hosts.yml playbooks/deploy.yml
```

### Smoke Tests

After deployment, run smoke tests:
```bash
cd api
uv run pytest tests/smoke/ -m smoke -v
# Or use the CLI runner
uv run python scripts/smoke_test.py --url https://api.menos.example.com -v
```
