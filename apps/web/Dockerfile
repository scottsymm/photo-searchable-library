FROM node:24-alpine AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN corepack enable && pnpm install --frozen-lockfile
COPY apps/web apps/web
RUN pnpm --dir apps/web build

FROM node:24-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY LICENSE /LICENSE
COPY --from=build /app/apps/web/.next/standalone ./
# The standalone server lives under apps/web, so static assets must be relative
# to that directory as well.
COPY --from=build /app/apps/web/.next/static ./apps/web/.next/static
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
