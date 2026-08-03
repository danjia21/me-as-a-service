FROM node:24.11.1-alpine3.22 AS builder

ARG CLOUDFLARE_ANALYTICS_SITE_TOKEN
ENV CLOUDFLARE_ANALYTICS_SITE_TOKEN=${CLOUDFLARE_ANALYTICS_SITE_TOKEN} \
    NEXT_TELEMETRY_DISABLED=1 \
    PNPM_HOME=/pnpm
ENV PATH="${PNPM_HOME}:${PATH}"

WORKDIR /build

RUN corepack enable \
    && corepack prepare pnpm@11.15.1 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY apps/api/package.json apps/api/package.json
RUN pnpm install --frozen-lockfile --filter @me-as-a-service/web...

COPY apps/web apps/web
COPY examples/fictional-profile examples/fictional-profile
RUN pnpm --filter @me-as-a-service/web build

FROM node:24.11.1-alpine3.22 AS runtime

ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

WORKDIR /app

COPY --from=builder --chown=node:node /build/apps/web/.next/standalone ./
COPY --from=builder --chown=node:node /build/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=node:node /build/examples/fictional-profile /app/examples/fictional-profile

USER node

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"]

CMD ["node", "apps/web/server.js"]
