---
name: python-fastapi-async-patterns
description: In a FastAPI service, an `async def` endpoint that calls a sync I/O library (psycopg2, requests, sqlite3, redis) blocks the event loop. Either keep the endpoint `def` (FastAPI runs it in a threadpool) or switch to the async-aware client (asyncpg, httpx.AsyncClient, aiosqlite, redis.asyncio).
audience: [worker]
triggers:
  language: [Python]
  keywords: [fastapi, endpoint, route, async, await, asyncio, uvicorn]
---

# FastAPI — async vs sync I/O

An `async def` endpoint that calls a **synchronous** I/O library (psycopg2, requests, sqlite3, redis, smtplib, boto3) blocks the entire event loop while the call waits on the network or disk. Throughput collapses and one slow query stalls every concurrent request.

FastAPI gives two correct shapes — pick one per endpoint and stick to it.

## The trap

```python
# ❌ async endpoint + sync DB client → event loop blocked
@app.get("/users/{uid}")
async def get_user(uid: int):
    with psycopg2.connect(DB_URL) as conn:  # blocks the loop
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (uid,))
        return cur.fetchone()
```

Looks asynchronous, isn't. Every call serializes through this endpoint.

## Two correct shapes

### Shape A — `def` endpoint, sync client (FastAPI runs in threadpool)

```python
# ✅ sync endpoint with sync DB — FastAPI offloads to threadpool
@app.get("/users/{uid}")
def get_user(uid: int):
    with psycopg2.connect(DB_URL) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (uid,))
        return cur.fetchone()
```

Choose this when the project already uses a sync stack and the request volume is moderate.

### Shape B — `async def` endpoint, async client

```python
# ✅ fully async path
@app.get("/users/{uid}")
async def get_user(uid: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.id == uid)
    )
    return result.scalar_one_or_none()
```

Choose this when expected concurrency is high or downstream calls are I/O-bound (HTTP, queue, websocket).

## Hard rules

- Never mix shapes inside one endpoint: `async def` + sync I/O is the bug.
- HTTP calls inside `async def` → `httpx.AsyncClient`, never `requests`.
- Database inside `async def` → `asyncpg`, `databases`, or SQLAlchemy `AsyncSession`. Never `psycopg2` / `sqlite3` direct.
- CPU-bound work in any endpoint → `await loop.run_in_executor(...)` or `anyio.to_thread.run_sync(...)`. A 500 ms hash inside an async endpoint freezes every other request for 500 ms.
- Dependency injection lives in `Depends(...)`, not in module-level globals — testability and request-scoping both depend on it.

## Allowed sync calls inside `async def`

CPU-bound, fast (< 1 ms), and non-blocking:

- pure-Python computation
- `pydantic` model construction / `.model_dump()`
- log calls (stdlib `logging` is non-blocking when stdout isn't a slow file)

Everything that touches the network, disk, or a subprocess does NOT belong here without the async client or a threadpool offload.

## Quick test

If `grep -nE 'async def.*\):' app/ | head` shows endpoints, then `grep -nE '(psycopg2|requests\.|sqlite3|smtplib)' app/` against the same files must return nothing. If it does, that's an async/sync mismatch waiting to ship.
