FROM python:3.12-slim

# Avoid bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy dependencies separately for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assets/municipality-ch.json assets/municipality-nl.json assets/municipality-sources.json assets/
COPY templates templates
COPY static static
COPY municipality_hunter municipality_hunter

USER 65534

# No default command: compose runs `init`, `sync --loop` and gunicorn from this image.
