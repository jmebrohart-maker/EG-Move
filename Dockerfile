# Use a slim python image (Debian based)
FROM python:3.11-slim

WORKDIR /app

# CRITICAL: Fixes OpenSSL (CVE-2025-69420) and other system-level vulnerabilities
# This runs apt-get upgrade to pull the latest security patches for Debian
RUN apt-get update && apt-get upgrade -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first to cache dependencies
COPY requirements.txt .

# SECURITY UPDATE: Fixes CVE-2026-24049 (wheel) and CVE-2025-8869 (pip)
# We strictly upgrade the build tools before installing packages
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Ensure storage directory exists
RUN mkdir -p storage

# Expose the port
EXPOSE 8000

# Run using Gunicorn (Production Server) instead of python main.py
# This utilizes the secure version of Gunicorn (22.0.0) we specified
CMD ["gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "--bind", "0.0.0.0:8000", "main:app"]