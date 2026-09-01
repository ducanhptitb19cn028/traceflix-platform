# TraceFlix web client.
#
# Build stage compiles the Vite SPA; the runtime stage carries only dist/ plus
# the Node host that serves it and proxies /api/* to the mesh. Vite 8 needs
# Node >= 22.12, so both stages pin node:22.
#
#   docker build -t traceflix/frontend:1.0.0 services/frontend
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
# server.js reads routes.js at import time; both are plain ESM with no deps, so
# the runtime stage needs no node_modules at all.
COPY --from=build /app/dist ./dist
COPY server.js routes.js package.json ./
EXPOSE 5173
# 0.0.0.0, not the 127.0.0.1 default: inside a pod the loopback is reachable
# only from this container, so the Service and the probes would never connect.
CMD ["node", "server.js", "--port", "5173", "--host", "0.0.0.0"]
