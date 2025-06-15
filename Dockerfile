FROM python:3.11-slim

# Avoid bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set a non-root writable working directory
WORKDIR /app

# Copy dependencies separately for caching
COPY requirements.txt .

# Install dependencies without cache
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Make sure the workdir is writable by any user (e.g., OpenShift’s random UID)
RUN chmod -R g+rw /app && \
    chgrp -R 0 /app

# Default command
CMD ["python", "collector.py"]
