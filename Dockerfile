FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TUNA_DATA_DIR=/data
WORKDIR /app/endless-tuna/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/endless_tuna ./endless_tuna
COPY --from=frontend /build/dist /app/endless-tuna/frontend/dist
RUN groupadd --gid 10001 tuna && useradd --uid 10001 --gid tuna --no-create-home tuna \
    && mkdir -p /data/demo-pdfs /data/real-pdfs && chown -R tuna:tuna /data
USER tuna
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "endless_tuna.main:app", "--host", "0.0.0.0", "--port", "8000"]
