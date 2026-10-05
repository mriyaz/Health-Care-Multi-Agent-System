# Security model

HealthOS is an engineering demonstration. Security architecture includes encryption expectations, access control, and auditability concepts. Formal compliance certification has not been performed. The project is not HIPAA certified, and this document is not a compliance attestation.

Designed with HIPAA-aligned security principles for a future deployment:

- JWT access tokens and rotating refresh tokens stored server-side
- Password hashes via bcrypt. The API does not store plaintext passwords
- Role checks on FHIR and task routes
- Tenant id taken from the authenticated principal and applied to queries
- A de-identification pass before an external model call on the documentation path
- Append-only audit rows for routing and human approval
- FHIR note write-back only after an authenticated approval

## Local development boundaries

Compose publishes PostgreSQL, Redis, Weaviate, and HAPI on localhost. Weaviate anonymous access is enabled for that local stack. Default passwords in Compose are placeholders marked local-development-only. Replace them before any shared network, and do not reuse them anywhere else.

`.env`, `infra/.env`, and `.local-demo-credentials` are gitignored. Only `.env.example` and `infra/.env.example` belong in Git, and those files contain placeholders such as `your_openrouter_api_key_here` and `replace_with_secure_random_value`.

Generate demo users locally:

```powershell
python -m scripts.seed_users --demo
```

Do not use demo credentials in production.

## Data

All included patient and clinical examples are synthetic and are provided solely for development and demonstration. Do not load real patient data, real audio, or production credentials into this tree.

## What this repository does not claim

- No medical-device status
- No unsupervised clinical decision-making
- No production penetration test
- No measured uptime or throughput
- No statement that de-identification meets a regulatory safe-harbor method

## Reporting

If you find a committed secret or a real patient artifact in this public repository, open a private security report to the maintainer and avoid pasting the secret into a public issue.
