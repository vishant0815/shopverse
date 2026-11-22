FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 \
    PYTHONPATH=/app

# Spark runs on the JVM. Spark 4.0 supports Java 17 and 21; Debian trixie ships 21.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set INSTALL_DEV=true to include test dependencies (used for local development and CI).
ARG INSTALL_DEV=false
COPY requirements.txt requirements-dev.txt ./
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; else pip install -r requirements.txt; fi

# Run as a non-root user. Spark keeps its downloaded connector jars in the home directory.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/analytics \
    && chown app:app /data/analytics
COPY --chown=app:app . .
USER app

# No HTTP port: this is a streaming job, not a service.
CMD ["spark-submit", \
     "--packages", "org.apache.spark:spark-sql-kafka-0-10_2.13:4.0.1", \
     "--conf", "spark.jars.ivy=/home/app/.ivy2", \
     "--master", "local[2]", \
     "/app/clickstream/job.py"]
