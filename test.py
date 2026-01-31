import os
import secrets
import string
import shutil
import logging
import time
import threading
import uuid
from typing import Dict, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends, Form, status
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Configuration ---
STORAGE_DIR = "storage"

# CREDENTIALS & SETTINGS
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ComplexPassword123!") 
# Initial Base URL from environment, can be updated at runtime by admin
INITIAL_BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# Global state for Base URL
APP_CONFIG = {
    "base_url": INITIAL_BASE_URL
}

os.makedirs(STORAGE_DIR, exist_ok=True)

app = FastAPI(title="EG-Move")

os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-Memory Database ---
FILE_DB: Dict[str, dict] = {}
ADMIN_SESSIONS = set()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("EG-Move")

# --- Utilities ---

def generate_code(length=6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = ''.join(secrets.choice(alphabet) for _ in range(length))
    return f"{raw[:3]}-{raw[3:]}"

def normalize_code_input(user_input: str) -> str:
    clean = user_input.replace("-", "").replace(" ", "").upper()
    if len(clean) == 6:
        return f"{clean[:3]}-{clean[3:]}"
    return clean

def format_size(size: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"

def cleanup_file(code: str):
    if code in FILE_DB:
        try:
            meta = FILE_DB[code]
            if os.path.exists(meta["path"]):
                os.remove(meta["path"])
                logger.info(f"Deleted file: {meta['path']}")
        except Exception as e:
            logger.error(f"Error cleaning up {code}: {e}")
        finally:
            if code in FILE_DB:
                del FILE_DB[code]

def monitor_expirations():
    while True:
        time.sleep(10) # Check every 10 seconds for better precision
        now = time.time()
        for code in list(FILE_DB.keys()):
            if code in FILE_DB:
                expires_at = FILE_DB[code]["expires_at"]
                if expires_at != float('inf') and now > expires_at:
                    logger.info(f"Expired: {code}")
                    cleanup_file(code)

@app.on_event("startup")
async def startup_event():
    threading.Thread(target=monitor_expirations, daemon=True).start()
    logger.info("Expiration monitor started.")

# --- Admin Dependencies ---

def get_current_admin(request: Request):
    token = request.cookies.get("admin_token")
    if not token or token not in ADMIN_SESSIONS:
        return None
    return token

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), duration: int = Form(10)):
    """Handles file upload with specific durations (10, 15, 30 mins)."""
    try:
        # Validate allowed durations (10, 15, 30). Default to 10 if hacked.
        if duration not in [10, 15, 30]:
            duration = 10

        code = generate_code()
        safe_filename = f"{code.replace('-', '')}_{file.filename}"
        file_path = os.path.join(STORAGE_DIR, safe_filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)
        
        # Calculate expiry
        expires_at = time.time() + (duration * 60)
        logger.info(f"Uploaded: {code} (Duration: {duration} mins)")

        FILE_DB[code] = {
            "path": file_path,
            "filename": file.filename,
            "size": file_size,
            "expires_at": expires_at
        }

        return {
            "status": "success", 
            "code": code, 
            "filename": file.filename, 
            "expires_in": duration * 60
        }
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Upload failed")

@app.get("/api/info/{code}")
async def get_file_info(code: str):
    code = normalize_code_input(code)
    if code not in FILE_DB:
        raise HTTPException(status_code=404, detail="Invalid code")
    
    meta = FILE_DB[code]
    
    if meta["expires_at"] == float('inf'):
        remaining = -1
    else:
        remaining = meta["expires_at"] - time.time()
        if remaining <= 0:
            cleanup_file(code)
            raise HTTPException(status_code=404, detail="Code expired")

    return {
        "valid": True,
        "filename": meta["filename"],
        "size": meta["size"],
        "expires_in_seconds": int(remaining) if remaining != -1 else -1
    }

@app.get("/api/download/{code}")
async def download_file(code: str):
    code = normalize_code_input(code)
    if code not in FILE_DB:
        raise HTTPException(status_code=404, detail="Invalid code")

    meta = FILE_DB[code]
    if meta["expires_at"] != float('inf') and time.time() > meta["expires_at"]:
        cleanup_file(code)
        raise HTTPException(status_code=404, detail="Code expired")

    return StreamingResponse(
        open(meta["path"], "rb"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{meta["filename"]}"'}
    )

# --- Admin Routes ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = str(uuid.uuid4())
        ADMIN_SESSIONS.add(token)
        response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="admin_token", value=token, httponly=True, max_age=3600)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})

@app.get("/logout")
async def logout(response: Response):
    resp = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("admin_token")
    return resp

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, user=Depends(get_current_admin)):
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    files_list = []
    total_size = 0
    now = time.time()
    
    for code, meta in list(FILE_DB.items()):
        total_size += meta["size"]
        if meta["expires_at"] == float('inf'):
            remaining_seconds = -1
        else:
            remaining = meta["expires_at"] - now
            remaining_seconds = int(remaining) if remaining > 0 else 0
            
        files_list.append({
            "code": code,
            "filename": meta["filename"],
            "size_str": format_size(meta["size"]),
            "expires_in": remaining_seconds
        })
        
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "files": files_list,
        "total_files": len(files_list),
        "total_storage": format_size(total_size),
        "base_url": APP_CONFIG["base_url"]
    })

@app.post("/api/admin/delete/{code}")
async def admin_delete(code: str, user=Depends(get_current_admin)):
    if not user:
        raise HTTPException(status_code=403, detail="Not authenticated")
    cleanup_file(code)
    return {"status": "deleted", "code": code}

@app.post("/api/admin/toggle_expiry/{code}")
async def admin_toggle_expiry(code: str, user=Depends(get_current_admin)):
    if not user:
        raise HTTPException(status_code=403, detail="Not authenticated")
    
    if code in FILE_DB:
        if FILE_DB[code]["expires_at"] == float('inf'):
            # If infinite, set to expire in 10 mins from NOW
            FILE_DB[code]["expires_at"] = time.time() + 600
            new_status = "timed"
        else:
            # If timed, set to infinite
            FILE_DB[code]["expires_at"] = float('inf')
            new_status = "infinite"
        return {"status": "success", "new_mode": new_status}
    
    raise HTTPException(status_code=404, detail="File not found")

@app.post("/api/admin/update_url")
async def admin_update_url(request: Request, user=Depends(get_current_admin)):
    if not user:
        raise HTTPException(status_code=403, detail="Not authenticated")
    
    data = await request.json()
    new_url = data.get("url", "").rstrip("/")
    if new_url:
        APP_CONFIG["base_url"] = new_url
        return {"status": "updated", "url": new_url}
    
    raise HTTPException(status_code=400, detail="Invalid URL")

if __name__ == "__main__":
    import uvicorn
    print("------------------------------------------------")
    print("Starting EG-Move server...")
    print(f"ACTIVE ADMIN USER:     {ADMIN_USERNAME}")
    print(f"ACTIVE ADMIN PASSWORD: {ADMIN_PASSWORD}")
    print(f"INITIAL BASE URL:      {INITIAL_BASE_URL}")
    print("------------------------------------------------")
    uvicorn.run(app, host="0.0.0.0", port=8000)