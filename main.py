import os
import secrets
import string
import shutil
import logging
from typing import Dict
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Configuration
# Changed to a relative path for easier local testing
STORAGE_DIR = "storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

app = FastAPI(title="EG-Move")

# Ensure the directory exists before mounting
os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

# Enable CORS for flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory database for MVP (Replace with Redis for multi-container scaling)
# Structure: { "CODE123": { "path": "...", "filename": "...", "size": 1024 } }
FILE_DB: Dict[str, dict] = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EG-Move")

def generate_code(length=6) -> str:
    """Generates a secure, easy-to-read 6-char code (e.g., A7B-9X2)."""
    alphabet = string.ascii_uppercase + string.digits
    raw = ''.join(secrets.choice(alphabet) for _ in range(length))
    return f"{raw[:3]}-{raw[3:]}"

def cleanup_file(filepath: str, code: str):
    """Deletes the file and metadata after successful download."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Deleted file: {filepath}")
        if code in FILE_DB:
            del FILE_DB[code]
            logger.info(f"Removed code from DB: {code}")
    except Exception as e:
        logger.error(f"Error cleaning up {code}: {e}")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the Frontend GUI."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handles unlimited size uploads via streaming."""
    try:
        code = generate_code()
        
        # Use a safe internal filename to prevent overwrites/path traversal
        safe_filename = f"{code.replace('-', '')}_{file.filename}"
        file_path = os.path.join(STORAGE_DIR, safe_filename)

        # Stream write to disk (Low Memory Usage)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)

        # Store Metadata
        FILE_DB[code] = {
            "path": file_path,
            "filename": file.filename,
            "size": file_size,
            "content_type": file.content_type
        }

        logger.info(f"File uploaded: {code} ({file_size} bytes)")
        return {"status": "success", "code": code, "filename": file.filename}

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

@app.get("/api/info/{code}")
async def get_file_info(code: str):
    """Returns metadata for the recipient before downloading."""
    code = code.upper() # Case insensitive
    if code not in FILE_DB:
        raise HTTPException(status_code=404, detail="Invalid code")
    
    meta = FILE_DB[code]
    return {
        "valid": True,
        "filename": meta["filename"],
        "size": meta["size"]
    }

@app.get("/api/download/{code}")
async def download_file(code: str, background_tasks: BackgroundTasks):
    """Streams the file to the recipient and deletes it afterwards."""
    code = code.upper()
    if code not in FILE_DB:
        raise HTTPException(status_code=404, detail="Invalid or expired code")

    meta = FILE_DB[code]
    file_path = meta["path"]

    # Schedule cleanup after response is sent (One-time transfer)
    background_tasks.add_task(cleanup_file, file_path, code)

    return StreamingResponse(
        open(file_path, "rb"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{meta["filename"]}"'}
    )

if __name__ == "__main__":
    import uvicorn
    print("Starting EG-Move server...")
    print("Ensure you have a 'templates' folder with 'index.html' inside.")
    uvicorn.run(app, host="0.0.0.0", port=8000)