FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Set INSTALL_DEV=true to include test dependencies (used for local development and CI).
ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; else pip install -r requirements.txt; fi

# Run as a non-root user.
RUN useradd --create-home --uid 1000 app
COPY --chown=app:app . .
USER app

EXPOSE 8000

# --no-proxy-headers: uvicorn would otherwise rewrite the caller's address from
# X-Forwarded-For on its own. The gateway reads that header itself, trusting only as
# many hops as TRUSTED_PROXY_HOPS says (see app/proxy.py).
# --no-access-log: the gateway writes its own, one JSON line per request.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--no-proxy-headers", "--no-server-header", "--no-access-log"]
