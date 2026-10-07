FROM python:3.11-slim

WORKDIR /app

# Upgrade pip and setuptools first — python:3.11-slim ships pip 24.x which
# lacks setuptools.backends required by setuptools>=68 build-backend.
RUN pip install --no-cache-dir --upgrade pip setuptools

# Install dependencies first (layer caching)
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"

# Copy application code
COPY . .

# Create data directory for SQLite file
RUN mkdir -p /app/data

EXPOSE 8000

# MANDATORY: --workers 1 — SQLite single-writer constraint.
# Multiple workers cause file lock contention and data corruption.
# This is a safety constraint, not a tuning parameter.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
