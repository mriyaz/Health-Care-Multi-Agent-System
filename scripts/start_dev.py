"""
HealthOS local dev startup — Docker infra, migrations, seeds, and API.

Brings up the full stack needed for checklist #100 (SOAP Note Review UI):
  1. Docker Compose (Postgres, Redis, Weaviate, HAPI FHIR)
  2. Alembic migrations
  3. Generated local demo users + synthetic HAPI FHIR demo data
  4. Uvicorn (foreground)

Usage (from repo root, venv activated):
  python scripts/start_dev.py
  python scripts/start_dev.py --skip-docker
  python scripts/start_dev.py --no-api
  python scripts/start_dev.py --skip-seed

Windows shortcut:
  .\\scripts\\start_dev.ps1
"""

from __future__ import annotations

import argparse
import os
import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.yml"
ENV_FILE = REPO_ROOT / ".env"
INFRA_ENV_FILE = REPO_ROOT / "infra" / ".env"
DEFAULT_FHIR_BASE = "http://localhost:8082/fhir"
API_HOST = "127.0.0.1"
API_PORT = 8000


def _run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        check=check,
        text=True,
        capture_output=capture,
    )


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        sys.exit(f"Required tool not found on PATH: {name}")


def _check_env() -> None:
    if not ENV_FILE.is_file():
        example = REPO_ROOT / ".env.example"
        hint = (
            f"Copy {example.name} to .env and fill in secrets."
            if example.is_file()
            else ""
        )
        sys.exit(f"Missing {ENV_FILE}. {hint}".strip())

    text = ENV_FILE.read_text(encoding="utf-8")
    warnings: list[str] = []
    for key in ("SESSION_SECRET_KEY", "JWT_SECRET_KEY", "DATABASE_URL"):
        if f"{key}=" not in text or f"{key}=\n" in text or f"{key}= " in text:
            warnings.append(key)
    if "OPENROUTER_API_KEY=" not in text and "XAI_API_KEY=" not in text:
        warnings.append("OPENROUTER_API_KEY (SOAP generation will fail without it)")

    if warnings:
        print("Warning: .env may be incomplete — check:", ", ".join(warnings))


def _compose_cmd(*args: str) -> list[str]:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE)]
    if INFRA_ENV_FILE.is_file():
        cmd.extend(["--env-file", str(INFRA_ENV_FILE)])
    cmd.extend(args)
    return cmd


def _wait_for_tcp(host: str, port: int, *, label: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"  {label} ready ({host}:{port})")
                return
        except OSError:
            time.sleep(2)
    sys.exit(f"Timed out waiting for {label} at {host}:{port} ({timeout_s:.0f}s)")


def _wait_for_http(url: str, *, label: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if 200 <= resp.status < 300:
                    print(f"  {label} ready ({url})")
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(3)
    sys.exit(f"Timed out waiting for {label} at {url} ({timeout_s:.0f}s)")


def _start_docker() -> None:
    print("\n=== Starting Docker infrastructure ===")
    _run(_compose_cmd("up", "-d"))
    _run(_compose_cmd("ps"))


def _wait_for_services(*, hapi_timeout_s: float) -> None:
    print("\n=== Waiting for services ===")
    _wait_for_tcp("localhost", 5432, label="PostgreSQL", timeout_s=90)
    _wait_for_tcp("localhost", 6379, label="Redis", timeout_s=60)
    _wait_for_tcp("localhost", 8080, label="Weaviate", timeout_s=60)
    # HAPI is slow on first boot — allow extra time for /metadata.
    _wait_for_http(
        "http://localhost:8082/fhir/metadata",
        label="HAPI FHIR",
        timeout_s=hapi_timeout_s,
    )


def _migrate() -> None:
    print("\n=== Running database migrations ===")
    alembic = shutil.which("alembic")
    if alembic:
        _run([alembic, "upgrade", "head"])
    else:
        _run([sys.executable, "-m", "alembic", "upgrade", "head"])


def _seed(*, fhir_base_url: str) -> None:
    print("\n=== Seeding users and FHIR demo data ===")
    _run([sys.executable, "-m", "scripts.seed_users", "--demo"])
    _run([sys.executable, "scripts/seed_hapi_fhir.py", "--base-url", fhir_base_url])


def _print_ready() -> None:
    print("\n=== HealthOS dev stack ready ===")
    print(f"  API docs:        http://{API_HOST}:{API_PORT}/docs")
    print(f"  SOAP review UI:  http://{API_HOST}:{API_PORT}/ui/soap-review/")
    print("  HAPI FHIR:       http://localhost:8082/fhir")
    print("\n  Sign in with the local demo user from .local-demo-credentials")
    print("  LOCAL DEVELOPMENT ONLY — NEVER USE IN PRODUCTION")
    print("  Flow: load demo encounter, generate SOAP, approve, write FHIR")


def _start_api() -> None:
    print("\n=== Starting FastAPI (Ctrl+C to stop) ===")
    uvicorn = shutil.which("uvicorn")
    cmd = (
        [
            uvicorn,
            "api.main:app",
            "--reload",
            "--host",
            API_HOST,
            "--port",
            str(API_PORT),
        ]
        if uvicorn
        else [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--reload",
            "--host",
            API_HOST,
            "--port",
            str(API_PORT),
        ]
    )
    try:
        _run(cmd)
    except KeyboardInterrupt:
        print("\nAPI stopped.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-docker",
        action="store_true",
        help="Skip docker compose up (infra already running).",
    )
    parser.add_argument(
        "--skip-migrate",
        action="store_true",
        help="Skip alembic upgrade head.",
    )
    parser.add_argument(
        "--skip-seed",
        action="store_true",
        help="Skip user + HAPI FHIR seeding.",
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="Prepare infra/DB/seeds only; do not start Uvicorn.",
    )
    parser.add_argument(
        "--fhir-base-url",
        default=os.getenv("HAPI_FHIR_BASE_URL", DEFAULT_FHIR_BASE),
        help=f"HAPI FHIR base URL for seeding (default: {DEFAULT_FHIR_BASE}).",
    )
    parser.add_argument(
        "--hapi-timeout",
        type=float,
        default=180.0,
        help="Seconds to wait for HAPI FHIR /metadata (default: 180).",
    )
    return parser.parse_args()


def main() -> None:
    if Path.cwd().resolve() != REPO_ROOT:
        os.chdir(REPO_ROOT)

    args = parse_args()

    _require_tool("docker")
    _check_env()

    if not args.skip_docker:
        _start_docker()
        _wait_for_services(hapi_timeout_s=args.hapi_timeout)
    elif not args.skip_seed or not args.skip_migrate:
        # Still verify core deps when skipping docker but running DB steps.
        _wait_for_tcp("localhost", 5432, label="PostgreSQL", timeout_s=30)

    if not args.skip_migrate:
        _migrate()

    if not args.skip_seed:
        _seed(fhir_base_url=args.fhir_base_url)

    _print_ready()

    if args.no_api:
        return

    _start_api()


if __name__ == "__main__":
    main()
