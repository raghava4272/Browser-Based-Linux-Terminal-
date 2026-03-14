# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# System deps (bash is always present in debian-slim; ptyprocess needs openpty)
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash \
      procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .
COPY index.html .

# ── Runtime ───────────────────────────────────────────────────────────────────
EXPOSE 8000

# Environment variables (override at runtime)
ENV TERMINAL_TOKEN=changeme-supersecret \
    IDLE_TIMEOUT=600 \
    PYTHONUNBUFFERED=1

# Run with uvicorn (single worker is fine; each WS gets its own coroutine)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
