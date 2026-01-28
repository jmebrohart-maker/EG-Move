# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Install python dependencies
# Create requirements.txt inline or copy it
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create volume mount point
RUN mkdir -p /app/data/uploads

# Expose the port
EXPOSE 8000

# Run with Gunicorn (Process Manager) + Uvicorn (Worker)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
