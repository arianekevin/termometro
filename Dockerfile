# Builds the collector for <script> tags, then runs the server (Python standard library only).
FROM node:22-alpine AS collector
WORKDIR /collector
COPY collector/package.json collector/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY collector/ ./
RUN mkdir -p ../server/static && npm run build

FROM python:3.12-alpine
WORKDIR /app
COPY server/termometro.py ./
COPY server/static ./static
COPY --from=collector /collector/dist/termometro.js ./static/termometro.js
RUN adduser -D -H termometro && mkdir /data && chown termometro /data
USER termometro
ENV TERMOMETRO_DB=/data/termometro.db TERMOMETRO_PORT=8080
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/api/me >/dev/null || exit 1
CMD ["python", "-u", "termometro.py"]
