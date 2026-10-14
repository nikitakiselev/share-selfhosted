# syntax=docker/dockerfile:1

# The frontend is plain static files: build it once on the build machine for every platform
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-alpine
RUN apk add --no-cache ffmpeg \
 && addgroup -g 1000 share \
 && adduser -D -H -u 1000 -G share share \
 && mkdir /data \
 && chown share:share /data
COPY backend/ /tmp/backend/
RUN pip install --no-cache-dir /tmp/backend && rm -rf /tmp/backend
COPY --from=frontend /src/dist /app/static
ENV PYTHONUNBUFFERED=1 \
    SHARE_DATA_DIR=/data \
    SHARE_STATIC_DIR=/app/static \
    SHARE_HOST=0.0.0.0 \
    SHARE_PORT=8000
USER share
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD wget -qO /dev/null "http://127.0.0.1:${SHARE_PORT}/healthz" || exit 1
CMD ["share-app"]
