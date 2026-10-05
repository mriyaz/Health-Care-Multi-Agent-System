# Local development

All included patient and clinical examples are synthetic and are provided solely for development and demonstration.

Create a local demo user with:

```powershell
python -m scripts.seed_users --demo
```

The command generates passwords, prints them once, and writes `.local-demo-credentials`. That file is gitignored. Re-running `--demo` replaces the local admin and clinician passwords. Do not use demo credentials in production.

## Environment

| File | Who reads it |
| --- | --- |
| `.env` | FastAPI and Alembic via `api/settings.py`. Not committed. |
| `infra/.env` | Docker Compose when you pass `--env-file`. Not committed. |
| `.env.example` and `infra/.env.example` | Placeholders only |

Required application settings:

- `SESSION_SECRET_KEY` and `JWT_SECRET_KEY`, each at least 32 characters
- `DATABASE_URL=postgresql+asyncpg://healthos:<password>@localhost:5432/healthos` for a host-run API
- `OPENROUTER_API_KEY` only if you want live model calls

Model ids are optional overrides. If you set one, set it once. Duplicate keys in `.env` are last-wins.

`HEALTHOS_ORCHESTRATOR_CHECKPOINTER` is `postgres` or `memory`.

`FHIR_ADAPTER_KIND` is `generic` or `example`.

## Commands

From the repository root, with the virtualenv activated:

```powershell
docker compose --env-file infra/.env -f infra/docker-compose.yml up -d
alembic upgrade head
python -m scripts.seed_users --demo
python scripts/seed_hapi_fhir.py --base-url http://localhost:8082/fhir
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Stop infrastructure:

```powershell
docker compose -f infra/docker-compose.yml down
```

Optional Langfuse overlay:

```powershell
docker compose --env-file infra/.env -f infra/docker-compose.yml -f infra/docker-compose.langfuse.yml up -d
```

The Langfuse file contains local-only placeholder secrets. Replace them before any shared deployment. Generate an encryption key with `python -c "import secrets; print(secrets.token_hex(32))"`.

Optional Whisper, not installed by `requirements.txt`:

```powershell
pip install openai-whisper
```

Set `HEALTHOS_SKIP_WHISPER=1` to force transcript-only intake.

## Demo flow

Open http://127.0.0.1:8000/ui/soap-review/. Sign in with the generated clinician user. Load demo encounters. Submit the synthetic transcript. Generate, review, edit, and approve. The approve action writes a `DocumentReference` for `Patient/healthos-sample-patient-001` on the local HAPI server.

## Tests

```powershell
black --check .
flake8 .
pytest
```

Postgres does not need to be running for the default suite. Redis tests skip when Redis is unreachable.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Task stays queued | Restart the API after code or env changes and create a new task. On Windows, `api/event_loop.py` must load, which `api/main.py` does. |
| Model HTTP 404 | The configured model id is not available to the API key. |
| SOAP text collapsed into one section | Regenerate after pulling the JSON parser used by `documentation_llm`. |
| FHIR validation error on write-back | Load the demo encounter so the note has FHIR ids, then retry approval. |
| Langfuse connection refused | Unset `LANGFUSE_*` or start the Langfuse overlay. |
