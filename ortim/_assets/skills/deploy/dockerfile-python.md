---
name: deploy-dockerfile-python
description: Multi-stage Python 3.12-slim Dockerfile with non-root user, pip install --no-cache, and a minimal runtime stage. Use when shipping a Python service (FastAPI, Flask, Django) for production deploy.
audience: [worker]
triggers:
  tier: [T4, T5, T6]
  app_class: [web]
  language: [Python]
  keywords: [deploy, deployment, production, containerize, docker, dockerfile, ship]
  keywords_blocklist: [no docker, without docker, lokal kalsın, lokal kalsin, local only, no container]
---

# Production Dockerfile — Python 3.12-slim

A Dockerfile that ships a Python web service to production. Two-stage so the runtime image carries only the installed packages and the application source, not the build toolchain.

## Template

```dockerfile
# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/install/bin:$PATH \
    PYTHONPATH=/install/lib/python3.12/site-packages
WORKDIR /app
RUN groupadd -g 10001 app && useradd -u 10001 -g app -M -s /usr/sbin/nologin app
COPY --from=build /install /install
COPY . .
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Required project structure

- `requirements.txt` checked in (or `pyproject.toml` with a lock file — adapt the build stage accordingly).
- Application module path is `app.main:app` (adjust the `CMD` if different).
- A `GET /health` endpoint returns `200`.

## Hard rules

- Use **`python:3.12-slim`** (or `python:3.12-slim-bookworm`), never `python:latest` or `python:3.12` (the full image carries ~1 GB of unused tooling).
- Build dependencies (`build-essential`, `gcc`, headers for native wheels) belong **only in the build stage**. The runtime image must not contain a C compiler.
- Run as a non-root user (`USER app`). Set `nologin` shell.
- Set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1` in the runtime so logs flush immediately and no `.pyc` litter the image.
- Include a `HEALTHCHECK` — orchestrators rely on it.
- Never `COPY .env` or any secrets into the image. Secrets come from runtime env vars or a secret manager.

## `.dockerignore` (write this alongside the Dockerfile)

```
.git
.env
.env.*
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
.venv
venv
dist
build
*.egg-info
coverage
.coverage
.DS_Store
```
