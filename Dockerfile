FROM python:3.11-slim AS build

# Avoid bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set a non-root writable working directory
WORKDIR /app

# Copy dependencies separately for caching
COPY requirements.txt .

# Install dependencies without cache
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt --target=/app/bin

FROM python:3.11-slim

ENV PYTHONPATH=/app/bin

WORKDIR /app

COPY --chown=65534:0 --from=build /app .
# Copy app code
COPY --chown=65534:0 assets assets
COPY --chown=65534:0 collector.py .

USER 65534

# Default command
ENTRYPOINT ["/usr/local/bin/python", "collector.py"]
