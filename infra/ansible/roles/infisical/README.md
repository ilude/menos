# Infisical Ansible Role

Deploys self-hosted Infisical behind Caddy with a dedicated Postgres container.

## Required vault variables

- `vault_infisical_encryption_key`: Infisical data encryption key. Generate a strong random value and store it in the password manager.
- `vault_infisical_auth_secret`: Infisical auth/JWT secret. Generate a strong random value and store it in the password manager.
- `vault_infisical_postgres_password`: Password for the dedicated `infisical` Postgres user.

## Required non-secret variables

- `infisical_domain`: Public DNS name, for example `infisical.example.com`.
- `infisical_caddy_email`: Email used for Caddy ACME registration.
- `infisical_deploy_path`: Directory where compose files are rendered. Defaults to `{{ deploy_path }}/infisical`.

## Notes

- Only Caddy binds host ports 80 and 443.
- Infisical and Postgres stay on Docker networks; Postgres is internal only.
- SMTP is intentionally not configured by default. Root account recovery is handled by the documented DB-edit runbook.
- The rendered `infisical.env` is mode `0600` and must never be committed.
