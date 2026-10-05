# Redis & Celery — next steps (learning tests)

Companion to [docs/development/redis_celery_and_sessions.md](../../docs/development/redis_celery_and_sessions.md) (architecture and env vars).

---

```bash
python -m pytest tests/redis_next_steps/ -v
```

or:

```bash
python -m unittest discover -s tests/redis_next_steps -p "test_*.py" -v
```

---

## What each piece teaches


| File                              | What it shows                                                                                                                                                                                                                               |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_worker_ping_unit.py`        | **Celery task as a plain function** — `worker_ping.run(...)` executes inside the test process with **no broker and no worker**. Use this to assert task logic is correct.                                                                   |
| `test_agent_events_pubsub.py`     | **Redis pub/sub** — one coroutine publishes via `publish_agent_event`, another subscription reads the JSON envelope. Same pattern a future SSE/WebSocket gateway would use (often in a **separate** process or long-lived task).            |
| `test_celery_broker_enqueue.py`   | **Broker only** — `worker_ping.delay(...)` hands a message to Redis. You get a `task_id` immediately; **no worker is required** for the message to be accepted.                                                                             |
| `test_celery_worker_roundtrip.py` | **Full path** — `delay` + `AsyncResult.get(timeout=...)`. Requires **Redis** and a **running Celery worker** (`celery -A api.tasks.celery_app worker`). If `get` times out, the task sat in the queue with nobody consuming it.             |
| `test_enqueue_http_miniapp.py`    | **HTTP → queue** — a **minimal FastAPI app** (defined only in the test) exposes `POST /dev/worker-ping`. Production will do the same on a real route: accept the request, enqueue, return `task_id`, let the client poll `GET /tasks/{id}`. |
| `listen_agent_events.py`          | **Blocking subscriber** — run in a second terminal to see messages; in another terminal trigger publishes (or run the pub/sub test). Uses **sync** Redis for simplicity.                                                                    |


---

## Prerequisites

1. **Redis** listening at `REDIS_URL` (default `redis://localhost:6379/0`).
2. For **worker round-trip** tests: start a worker from the repo root:
  ```bash
   celery -A api.tasks.celery_app worker --loglevel=info
  ```
3. Optional gate for the strictest Celery test: set `HEALTHOS_RUN_CELERY_INTEGRATION=1` so CI does not wait on a worker. Without it, the test **skips** unless the env var is set (see `test_celery_worker_roundtrip.py`).

---

## Mental model

1. **Session store** — handled in the main app (`RedisSessionMiddleware`); not duplicated here.
2. **Task queue** — API (or test) calls `.delay()` → message in Redis → **worker process** pops and runs `worker_ping`.
3. **Pub/sub** — fire-and-forget broadcast; subscribers can miss messages if they connect **after** publish. For “never miss” delivery you’d add Redis Streams or a DB outbox later.

---

## SSE / live UI (not implemented here)

To stream agent events to a browser you typically: **subscribe** to `healthos:agent:events` (or tenant channel) in a **dedicated async loop**, and **yield** `data: ...\n\n` chunks from a FastAPI `StreamingResponse`. Do **not** block the main request worker forever without careful design (timeouts, backpressure, auth).