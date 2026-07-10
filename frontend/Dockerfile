# Phase 10. Standalone output (next.config.ts) traces the minimal
# files/deps a production server needs — the final image copies just that,
# not the full node_modules tree.
FROM node:22-slim AS base
WORKDIR /app

FROM base AS deps
COPY package.json package-lock.json* ./
# `npm ci`, not `npm install`, would be the stricter choice — verified it
# fails here: the lockfile's optional wasm32-wasi fallback variant of
# @tailwindcss/oxide (never actually selected on either Windows dev or this
# Linux image, both of which have native platform binaries available) has
# an unresolvable upstream @emnapi/core version conflict that `npm ci`'s
# full cross-platform lockfile validation rejects outright, even though it
# doesn't affect what actually gets installed/used. `npm install` still
# respects the lockfile's version pins for every package that DOES resolve
# cleanly; it only tolerates the one already-broken optional fallback entry.
RUN npm install

FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are baked into the client bundle at build time, not
# read at container start — must be supplied as a build arg, not a runtime
# env var, or every browser request would silently hit the wrong API origin.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM base AS runtime
ENV NODE_ENV=production
RUN groupadd --system app && useradd --system --gid app app
COPY --from=builder /app/public ./public
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
USER app
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
