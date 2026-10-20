FROM python:3.13.7-slim-bookworm

LABEL org.opencontainers.image.title="FocalCove" \
      org.opencontainers.image.description="Focus companion web app and Android API" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/CGY2056666/focalcove"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FOCUS_ENV=production \
    FOCUS_TRUST_PROXY_HEADERS=true \
    USERS_JSON_PATH=/app/runtime/users.json \
    USER_DATA_JSON_DIR=/app/runtime/user_data \
    USER_HISTORY_JSON_DIR=/app/runtime/user_history \
    MOBILE_SESSIONS_JSON_PATH=/app/runtime/mobile_sessions.json \
    FOCUS_EVAL_CAPTURE_ENABLED=false

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py wsgi.py ./
COPY app ./app
COPY focus_engine ./focus_engine
COPY templates ./templates
COPY static ./static
COPY scripts/runtime_backup.py ./scripts/runtime_backup.py
COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md ./

RUN mkdir -p /app/runtime/user_data /app/runtime/user_history \
    && chown -R 65534:65534 /app/runtime

USER 65534:65534

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl --fail http://127.0.0.1:8000/health || exit 1

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:8000", "wsgi:app"]
