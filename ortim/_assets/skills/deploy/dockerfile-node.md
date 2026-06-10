---
name: deploy-dockerfile-node
description: Multi-stage Node 20-alpine Dockerfile with non-root user, npm ci, and a minimal runtime stage. Use when shipping a Node/TypeScript service for production deploy.
audience: [worker]
triggers:
  tier: [T4, T5, T6]
  app_class: [web]
  language: [TypeScript, JavaScript]
  keywords: [deploy, deployment, production, containerize, docker, dockerfile, ship]
  keywords_blocklist: [no docker, without docker, lokal kalsın, lokal kalsin, local only, no container]
---

# Production Dockerfile — Node 20-alpine

A Dockerfile that ships a Node/TypeScript service to production. Multi-stage so the runtime image carries only `node_modules --omit=dev` and the build output.

## Template

```dockerfile
# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --include=dev

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
RUN addgroup -g 10001 app && adduser -D -u 10001 -G app app
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/package-lock.json ./package-lock.json
RUN npm ci --omit=dev && npm cache clean --force
USER app
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:3000/health || exit 1
CMD ["node", "dist/index.js"]
```

## Required project structure

- `package.json` declares a `build` script that compiles into `dist/`.
- `package-lock.json` is checked in (`npm ci` requires it).
- Application listens on the port given by `process.env.PORT ?? 3000` and exposes `GET /health → 200`.

## Hard rules

- Use **`npm ci`**, never `npm install`, in the image — lockfile is the source of truth.
- The runtime stage **must not** install build toolchains (no `python3`, no `make`, no `g++`). If a native dep needs them, install only in the `deps` or `build` stage.
- Run as a non-root user (`USER app`). Containers running as root in production are a defense-in-depth gap.
- `ENV NODE_ENV=production` is set in the runtime stage so packages drop dev-only branches.
- Include a `HEALTHCHECK` — orchestrators rely on it for restart and rollout logic.
- Never `COPY .env` into the image. Secrets come from the runtime via env vars or a secret manager.

## `.dockerignore` (write this alongside the Dockerfile)

```
node_modules
dist
.git
.env
.env.*
*.log
coverage
.DS_Store
```
