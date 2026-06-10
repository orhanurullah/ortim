---
name: deploy-docker-compose-microservices
description: Multi-service docker-compose template for T5/T6 (microservices, event-driven). Defines per-service build, healthcheck, network, and an example of a shared message broker (Redis/Postgres). Use when shipping more than one independently-deployable service in the same project.
audience: [worker]
triggers:
  tier: [T5, T6]
  app_class: [web]
  keywords: [deploy, deployment, production, microservices, docker, docker-compose, compose, services, ship]
  keywords_blocklist: [no docker, without docker, lokal kalsın, lokal kalsin, local only, no container]
---

# docker-compose template — Microservices / Event-driven

A baseline `compose.yaml` for projects with two or more independently-deployable services plus shared infrastructure (DB, broker). Use this as a starting point — adapt service names, ports, and the broker choice to the RFC.

## Template

```yaml
# compose.yaml
services:
  api:
    build:
      context: ./services/api
      dockerfile: Dockerfile
    environment:
      DATABASE_URL: postgres://app:${DB_PASSWORD}@db:5432/app
      BROKER_URL: redis://broker:6379/0
    depends_on:
      db:
        condition: service_healthy
      broker:
        condition: service_healthy
    networks:
      - backend
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--spider", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    restart: unless-stopped

  worker:
    build:
      context: ./services/worker
      dockerfile: Dockerfile
    environment:
      BROKER_URL: redis://broker:6379/0
      DATABASE_URL: postgres://app:${DB_PASSWORD}@db:5432/app
    depends_on:
      broker:
        condition: service_healthy
      db:
        condition: service_healthy
    networks:
      - backend
    healthcheck:
      test: ["CMD", "pgrep", "-f", "worker"]
      interval: 30s
      timeout: 5s
      retries: 3
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DB_PASSWORD:?DB_PASSWORD required}
      POSTGRES_DB: app
    volumes:
      - db-data:/var/lib/postgresql/data
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  broker:
    image: redis:7-alpine
    networks:
      - backend
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped

networks:
  backend:
    driver: bridge

volumes:
  db-data:
```

## Required project structure

```
services/
  api/Dockerfile
  worker/Dockerfile
compose.yaml
.env.example     # documents DB_PASSWORD and any service-specific vars
```

Each service directory carries its own Dockerfile (see `deploy-dockerfile-node` or `deploy-dockerfile-python` skills for per-language templates).

## Hard rules

- Every service has a `healthcheck`. `depends_on` uses `condition: service_healthy`, not the bare form — without it, the dependent container starts before the dependency is ready and fails on first request.
- Use a **named network** (`backend`) so services address each other by service name (`db`, `broker`), never by container name or IP.
- Use **named volumes** for stateful services (`db-data`). Bind mounts (`./data:/var/lib/postgresql/data`) are for development only.
- Secrets come from `.env` (referenced via `${VAR}`) or a secret manager. Never inline a password literal in `compose.yaml`. The `${DB_PASSWORD:?DB_PASSWORD required}` form fails fast if the env var is missing.
- `restart: unless-stopped` on every long-running service.
- The compose file lives at the **repo root**, not inside a service directory.

## `.dockerignore` (write one per service directory)

Each `services/<name>/.dockerignore` follows the language-specific pattern (see Node / Python skills).
