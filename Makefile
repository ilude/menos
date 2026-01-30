.PHONY: deploy update backup shell build logs status test lint

# Ansible container commands
ANSIBLE_CMD = docker compose -f infra/ansible/docker-compose.yml run --rm ansible

# Full deploy: sync files, pull images, start services
deploy:
	$(ANSIBLE_CMD) playbooks/deploy.yml

# Quick update: pull latest images and restart
update:
	$(ANSIBLE_CMD) playbooks/update.yml

# Backup current server config
backup:
	$(ANSIBLE_CMD) playbooks/backup.yml

# Interactive shell in Ansible container
shell:
	docker compose -f infra/ansible/docker-compose.yml run --rm --entrypoint /bin/bash ansible

# Build Ansible container
build:
	docker compose -f infra/ansible/docker-compose.yml build

# Local development
dev:
	docker compose -f infra/ansible/files/menos/docker-compose.yml up -d

dev-down:
	docker compose -f infra/ansible/files/menos/docker-compose.yml down

dev-logs:
	docker compose -f infra/ansible/files/menos/docker-compose.yml logs -f

status:
	docker compose -f infra/ansible/files/menos/docker-compose.yml ps

# API development
api-build:
	docker compose -f infra/ansible/files/menos/docker-compose.yml build menos-api

# Run API tests
test:
	cd api && uv run pytest -v

# Run linter
lint:
	cd api && uv run ruff check .

# Format code
fmt:
	cd api && uv run ruff format .

# Test infrastructure
test-infra:
	@echo "Checking Ansible syntax..."
	$(ANSIBLE_CMD) --syntax-check playbooks/deploy.yml
	$(ANSIBLE_CMD) --syntax-check playbooks/update.yml
	$(ANSIBLE_CMD) --syntax-check playbooks/backup.yml
	@echo "All playbooks OK"
