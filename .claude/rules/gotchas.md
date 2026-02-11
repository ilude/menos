# Gotchas

## CRLF/LF in Ansible Container
Windows git uses `core.autocrlf=input` — stores LF in index, CRLF on disk. The Linux Ansible container must also set `core.autocrlf=input` or `git status` reports every text file as modified. This is handled in deploy.yml pre-flight block.

## Git safe.directory in Containers
Git 2.35.2+ rejects operations on repos owned by different UIDs. Mounted `/project` in Docker needs `git config --global --add safe.directory /project` before any git commands.

## Ansible Container Image Cache
Changes to `infra/ansible/Dockerfile` require explicit rebuild: `docker compose build --no-cache ansible`. The old cached image runs silently otherwise.

## Docker ARG Placement
`ARG GIT_SHA` changes every commit. Place after all `COPY` and `RUN` steps in Dockerfile to avoid busting the dependency install cache layer.

## Mock side_effect for Paginated Loops
A while loop calling a paginated method needs N+1 mock `side_effect` entries — N for data batches plus 1 empty return `([], total)` to break the loop. Missing the terminator causes `StopIteration`.

## SurrealDB RecordID Objects
The surrealdb Python client returns `RecordID` objects (not strings) for `id`, `source`, `target`, and other reference fields. Always convert before passing to Pydantic models. Use the `_stringify_record_id()`, `_parse_content()`, `_parse_chunk()`, `_parse_link()`, or `_parse_entity()` helpers in `storage.py`. Unit tests with mocked DB won't catch this — smoke tests against the live API are the safety net.
