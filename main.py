import os
import secrets
import string
import shutil
import logging
import time
import threading
from typing import Dict, List
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# Configuration
STORAGE_DIR = "storage"
EXPIRY_SECONDS = 600  # 10 Minutes
os.makedirs(STORAGE_DIR, exist_ok=True)

app = FastAPI(title="EG-Move")

# Ensure the directory exists before mounting
os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory database
# Structure: { "CODE123": { "path": "...", "filename": "...", "expires_at": 1700000000.0 } }
FILE_DB: Dict[str, dict] = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EG-Move")

def generate_code(length=6) -> str:
    """Generates a secure, easy-to-read 6-char code (e.g., A7B-9X2)."""
    alphabet = string.ascii_uppercase + string.digits
    raw = ''.join(secrets.choice(alphabet) for _ in range(length))
    return f"{raw[:3]}-{raw[3:]}"

def normalize_code_input(user_input: str) -> str:
    """
    Helper to make code entry flexible.
    Converts 'abc123', 'ABC 123', or 'abc-123' to 'ABC-123'.
    """
    # Remove existing hyphens and spaces, convert to upper
    clean = user_input.replace("-", "").replace(" ", "").upper()
    
    # If we have exactly 6 characters, assume it's the code and re-format to match DB key
    if len(clean) == 6:
        return f"{clean[:3]}-{clean[3:]}"
    
    # Otherwise return as is (it will likely fail the DB lookup)
    return clean

def cleanup_file(code: str):
    """Deletes the file and metadata."""
    if code in FILE_DB:
        try:
            meta = FILE_DB[code]
            filepath = meta["path"]
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Expired/Deleted file: {filepath}")
        except Exception as e:
            logger.error(f"Error cleaning up {code}: {e}")
        finally:
            del FILE_DB[code]
            logger.info(f"Removed code from DB: {code}")

def monitor_expirations():
    """Background thread to check for expired files every minute."""
    while True:
        time.sleep(60)  # Check every minute
        now = time.time()
        # Create a list of keys to avoid 'dictionary changed size during iteration' error
        codes_to_check = list(FILE_DB.keys())
        
        for code in codes_to_check:
            if code in FILE_DB:
                if now > FILE_DB[code]["expires_at"]:
                    logger.info(f"Time limit reached for {code}. Cleaning up.")
                    cleanup_file(code)

@app.on_event("startup")
async def startup_event():
    """Start the background cleaner thread on server start."""
    cleaner_thread = threading.Thread(target=monitor_expirations, daemon=True)
    cleaner_thread.start()
    logger.info("Background expiration monitor started.")

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serves the Frontend GUI."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Handles unlimited size uploads via streaming."""
    try:
        code = generate_code()
        
        # Use a safe internal filename
        safe_filename = f"{code.replace('-', '')}_{file.filename}"
        file_path = os.path.join(STORAGE_DIR, safe_filename)

        # Stream write to disk
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)

        # Store Metadata with Expiration Time
        FILE_DB[code] = {
            "path": file_path,
            "filename": file.filename,
            "size": file_size,
            "content_type": file.content_type,
            "expires_at": time.time() + EXPIRY_SECONDS
        }

        logger.info(f"File uploaded: {code} ({file_size} bytes). Expires in 10 mins.")
        return {"status": "success", "code": code, "filename": file.filename, "expires_in": EXPIRY_SECONDS}

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

@app.get("/api/info/{code}")
async def get_file_info(code: str):
    """Returns metadata for the recipient."""
    # Normalize input: "abc123" becomes "ABC-123" to match DB key
    code = normalize_code_input(code)

    if code not in FILE_DB:
        raise HTTPException(status_code=404, detail="Invalid code")
    
    meta = FILE_DB[code]
    remaining = meta["expires_at"] - time.time()
    
    if remaining <= 0:
        cleanup_file(code)
        raise HTTPException(status_code=404, detail="Code expired")

    return {
        "valid": True,
        "filename": meta["filename"],
        "size": meta["size"],
        "expires_in_seconds": int(remaining)
    }

@app.get("/api/download/{code}")
async def download_file(code: str):
    """Streams the file. Does NOT delete immediately."""
    # Normalize input: "abc123" becomes "ABC-123" to match DB key
    code = normalize_code_input(code)

    if code not in FILE_DB:
        raise HTTPException(status_code=404, detail="Invalid or expired code")

    meta = FILE_DB[code]
    
    # Double check expiry in case the background thread hasn't run yet
    if time.time() > meta["expires_at"]:
        cleanup_file(code)
        raise HTTPException(status_code=404, detail="Code expired")

    file_path = meta["path"]

    return StreamingResponse(
        open(file_path, "rb"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{meta["filename"]}"'}
    )

if __name__ == "__main__":
    import uvicorn
    print("Starting EG-Move server...")
    print("Files will remain valid for 10 minutes after upload.")
    uvicorn.run(app, host="0.0.0.0", port=8000)