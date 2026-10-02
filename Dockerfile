# One Cloud Run service: the FastAPI backend also serves the built React app.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/throughline ./throughline
COPY --from=web /web/dist ./static
# Single worker: background ingestion and per-student locks live in-process.
CMD exec uvicorn throughline.api:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75
