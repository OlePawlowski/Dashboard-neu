# Multi-stage build: build the Vite calculator, then run Flask with Gunicorn

# ---------- Builder: Node to build static calculator ----------
FROM node:20-alpine AS builder
WORKDIR /app

# Only install node deps for the main Vite-App (Kostenrechner) zuerst für besseres Caching
COPY package*.json ./
RUN npm ci

# Copy the rest of the repo (inkl. sevdesk_src) und baue den Kostenrechner
COPY . .
RUN npm run build

# ---------- Builder 2: Sevdesk-Rechnungsmodul ----------
FROM node:20-alpine AS sevdesk-builder
WORKDIR /app

# Nur Sevdesk-Projekt-Dateien kopieren
COPY sevdesk_src/Sevdesk/package*.json ./
RUN npm ci

COPY sevdesk_src/Sevdesk ./
RUN npm run build

# ---------- Runtime: Python with Gunicorn ----------
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (including WeasyPrint dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgobject-2.0-0 \
    libglib2.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
  && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

# App code
COPY . .

# Bring in built calculator assets
COPY --from=builder /app/static/kostenrechner ./static/kostenrechner

# Bring in built invoices (Sevdesk) assets
COPY --from=sevdesk-builder /app/dist ./static/rechnungen

# Railway provides $PORT
CMD ["bash", "-lc", "exec gunicorn app:app -b 0.0.0.0:${PORT}"]

