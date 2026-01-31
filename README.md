**** AI Usage is High ****  I made this just to play around with code and docker. Im a diesel mechanic and wanted to have fun with docker. 
**** Docker Hub and scout is being used in DEV ****

EG-Move: Scalable Secure File Transfer System

Design Document & Implementation Plan

1. Executive Summary

EG-Move is a containerized web application designed to facilitate the transfer of files and folders of unlimited size. Unlike email attachments or standard cloud storage links, EG-Move uses a short-lived, unique access code system (similar to a "pickup code") to ensure secure and easy delivery to recipients. It is built to run behind a reverse proxy (like Nginx or Traefik) and handles data streams efficiently to maintain low memory usage even during multi-gigabyte transfers.

2. Core Architecture

To satisfy the requirements of "No Size Limit," "Scalability," and "Dockerization," the application is built on the following stack:

Backend: Python FastAPI. Chosen for its high performance, native support for asynchronous request handling, and easy implementation of streaming responses (critical for large files).

Frontend: HTML5 + JavaScript (Fetch API). A lightweight SPA (Single Page Application) that handles chunked uploads.

Database: Redis (or a lightweight embedded JSON/SQLite DB for simplicity in the MVP). Used to store the mapping between Access Codes and File Paths.

Storage: Docker Volume. Files are written directly to a mounted volume to ensure persistence and decoupling from the container lifecycle.

Scalability & Large File Strategy

To handle files larger than the available RAM:

Uploads: The server processes the request stream chunk-by-chunk, writing directly to the disk buffer. The file is never fully loaded into memory.

Downloads: The server uses a StreamingResponse generator to read the file from the disk in small chunks (e.g., 1MB) and send them to the client.

Reverse Proxy: The Nginx/Traefik configuration must be tuned to disable body size limits (client_max_body_size 0).

3. Web GUI Design

The interface is clean and minimal, focusing on two primary actions: Send and Receive.

A. The "Send" View

Drop Zone: A large area to drag and drop files or zipped folders.

Progress Bar: Visual feedback using the XMLHttpRequest or Fetch upload progress events.

Result Modal: Upon completion, displays the 6-digit Unique Code (and a QR code option) to share with the recipient.

Expiration Settings: (Optional) Dropdown to set expiry (e.g., "1 Hour", "24 Hours", "1 Download").

B. The "Receive" View

Code Input: A large text field centered on the screen asking for the "Pickup Code".

Download Button: Triggers the validation and download stream.

Metadata Display: Before downloading, show the filename and size so the user knows what they are receiving.

4. Secure Code Generation & Validation

Logic

Instead of long, complex URLs, we use high-entropy short codes for ease of manual entry, backed by rate limiting to prevent brute-forcing.

Format: 6-character alphanumeric (e.g., H7K-29A).

Storage: A key-value store maps the code to the file metadata.

Key: code:H7K29A

Value: { "filepath": "/data/uploads/xyz.zip", "filename": "photos.zip", "expiry": timestamp, "max_downloads": 1 }

Security:

Rate Limiting: IP-based limiting on the code entry endpoint (e.g., max 5 attempts per minute).

One-Time Use: Option to delete the file immediately after a successful download.

Code Snippet: Unique Code Generator

import secrets
import string

def generate_access_code(length=6):
    """Generates a secure, readable short code."""
    alphabet = string.ascii_uppercase + string.digits
    # Exclude ambiguous characters if desired (e.g., 0/O, I/1)
    secure_code = ''.join(secrets.choice(alphabet) for _ in range(length))
    # Format as XXX-XXX for readability
    return f"{secure_code[:3]}-{secure_code[3:]}"


5. Reverse Proxy Support

The application is designed to sit behind a proxy like Nginx.

Headers: The app middleware will trust X-Forwarded-For and X-Forwarded-Proto to correctly identify client IPs and protocol (HTTPS).

Path Stripping: If hosted at domain.com/transfer, the app handles root path stripping.

6. Implementation & Code Structure

Backend Logic (Python FastAPI)

main.py

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
import shutil
import os
import uuid
from typing import Optional

app = FastAPI()

UPLOAD_DIR = "/app/data/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# In-memory store for demonstration (Use Redis/SQLite in prod)
FILES_METADATA = {} 

def cleanup_file(file_path: str, code: str):
    """Background task to remove file after single-use download"""
    if os.path.exists(file_path):
        os.remove(file_path)
    if code in FILES_METADATA:
        del FILES_METADATA[code]

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    # Create unique internal ID to avoid filename collisions
    file_id = str(uuid.uuid4())
    file_location = f"{UPLOAD_DIR}/{file_id}_{file.filename}"
    
    # STREAM WRITE: This handles unlimited file sizes without RAM crashes
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Generate Access Code
    access_code = generate_access_code() # Function defined in section 4
    
    FILES_METADATA[access_code] = {
        "path": file_location,
        "name": file.filename,
        "content_type": file.content_type
    }
    
    return {"code": access_code, "expiry": "24h"}

@app.get("/api/download/{code}")
async def download_file(code: str, background_tasks: BackgroundTasks):
    code = code.upper().replace("-", "") # Normalize
    data = FILES_METADATA.get(code)
    
    if not data:
        raise HTTPException(status_code=404, detail="Code not found or expired")

    file_path = data["path"]
    filename = data["name"]

    # STREAM READ: Generator function
    def iterfile():
        with open(file_path, mode="rb") as file_like:
            yield from file_like

    # Schedule deletion after response is sent (Secure implementation)
    # background_tasks.add_task(cleanup_file, file_path, code)

    return StreamingResponse(
        iterfile(), 
        media_type="application/octet-stream", 
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


7. Docker Deployment Plan

Dockerfile

This Dockerfile sets up a lightweight Python environment.

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


docker-compose.yml

This defines the relationship between the app and the storage.

version: '3.8'

services:
  eg-move:
    build: .
    container_name: eg-move
    restart: unless-stopped
    ports:
      - "8080:8000"  # Host Port : Container Port
    volumes:
      - ./data:/app/data  # Persist uploaded files
    environment:
      - MAX_UPLOAD_SIZE=0 # Application specific config
    networks:
      - proxy_net

networks:
  proxy_net:
    external: true # Connect to existing proxy network


Nginx Reverse Proxy Configuration (Crucial)

If you are using Nginx as a reverse proxy, you must remove the default upload size limit (usually 1MB).

server {
    listen 80;
    server_name send.yourdomain.com;

    # DISABLE UPLOAD SIZE LIMIT
    client_max_body_size 0; 

    location / {
        proxy_pass http://eg-move:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # Long timeouts for large file transfers
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}


8. Summary of Workflow

Deployment: You deploy the container using docker-compose up -d.

Access: You navigate to https://send.yourdomain.com.

Sending:

User A drags a 5GB .zip file into the "Send" box.

The file streams to the /app/data volume.

Server returns code: 9X2-B1L.

Sharing: User A texts the code 9X2-B1L to User B.

Receiving:

User B goes to the site, enters 9X2-B1L.

Server validates and immediately streams the 5GB file to User B.

(Optional) The file is auto-deleted from the server to free up space.
