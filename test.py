import os
import shutil
import pytest
from fastapi.testclient import TestClient
from main import app, STORAGE_DIR, FILE_DB

client = TestClient(app)

# Helper to clean up storage after tests
@pytest.fixture(autouse=True)
def clean_storage():
    # Setup: Create storage dir if not exists
    os.makedirs(STORAGE_DIR, exist_ok=True)
    yield
    # Teardown: Clean up files created during tests
    if os.path.exists(STORAGE_DIR):
        for filename in os.listdir(STORAGE_DIR):
            file_path = os.path.join(STORAGE_DIR, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
    FILE_DB.clear()

def test_read_root_exists():
    """Test that the root endpoint serves HTML."""
    # This expects templates/index.html to exist
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]

def test_upload_flow():
    """Test uploading a file and retrieving its code."""
    file_content = b"This is a test file."
    files = {"file": ("test.txt", file_content, "text/plain")}
    
    response = client.post("/api/upload", files=files)
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "code" in data
    assert data["filename"] == "test.txt"
    
    # Verify it exists in DB
    code = data["code"]
    assert code in FILE_DB

def test_info_retrieval():
    """Test retrieving metadata for an uploaded file."""
    # 1. Upload
    files = {"file": ("info_test.txt", b"Metadata check", "text/plain")}
    upload_res = client.post("/api/upload", files=files)
    code = upload_res.json()["code"]
    
    # 2. Get Info
    response = client.get(f"/api/info/{code}")
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["filename"] == "info_test.txt"

def test_download_and_cleanup():
    """Test downloading the file and ensuring it is deleted properly."""
    # 1. Upload
    content = b"Secret payload"
    files = {"file": ("secret.txt", content, "text/plain")}
    upload_res = client.post("/api/upload", files=files)
    code = upload_res.json()["code"]
    
    # 2. Download
    response = client.get(f"/api/download/{code}")
    assert response.status_code == 200
    assert response.content == content
    
    # 3. Verify Cleanup
    # TestClient triggers background tasks on response close.
    assert code not in FILE_DB

def test_invalid_code():
    """Test 404 for non-existent codes."""
    response = client.get("/api/download/INVALID-CODE")
    assert response.status_code == 404