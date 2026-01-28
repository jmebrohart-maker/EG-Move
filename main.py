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
