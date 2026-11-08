# JobPilot backend (hosted mode). The UI is deployed separately (Vercel) and proxies /api here.
# Build context = repo root:  docker build -t jobpilot-api .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOSTED=1 \
    DATA_DIR=/data \
    MAX_UPLOAD_MB=4

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ .

# run as an unprivileged user; /data is the (volume-mounted) home of uploads and generated documents
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz',timeout=4)"

# exactly ONE process: the scheduler (job polling, email checks, autopilot) runs inside it
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
