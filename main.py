from fastapi import FastAPI, Depends
import re
from fastapi.responses import FileResponse, RedirectResponse
from fastapi import HTTPException, File, UploadFile
from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import os
import secrets
from typing import Optional
import json

app = FastAPI()
valid_channel_name = re.compile(
    "^[a-z0-9_]+$"
)  # Notably don't allow any ./ or anything that could cause a directory traversal
security = HTTPBasic()

wheel_url_cache: Optional[dict[str, str]] = None


def authenticated(
    credentials: HTTPBasicCredentials = Depends(security),
) -> HTTPBasicCredentials:
    username = os.getenv("REPO_USERNAME")
    password = os.getenv("REPO_PASSWORD")
    if not username or not password:
        raise HTTPException(status_code=500, detail="Server not configured correctly")
    if not secrets.compare_digest(credentials.username.encode(), username.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not secrets.compare_digest(credentials.password.encode(), password.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return credentials


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/channels/{channel_name}/{arch}/repodata.json")
async def get_repodata(channel_name: str, arch: str):
    file_path = get_repodata_file(channel=channel_name, arch=arch)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)

@app.get("/channels/{channel_name}/{arch}/{filename}.whl")
async def get_wheel(filename: str):
    # Wheels are always in the format package-version-build-num.whl
    # And the build number is actually the key to look up in the index, instead of anything meaningful
    parts = filename.split("-")
    key = parts[-1]
    cache = get_wheel_url_cache()
    if key not in cache:
        raise HTTPException(status_code=404, detail="File not found")
    return RedirectResponse(cache[key])
    

@app.post("/channels/{channel_name}/{arch}/repodata.json")
async def set_repodata(
    channel_name: str,
    arch: str,
    file: UploadFile = File(...),
    _authenticated: HTTPBasicCredentials = Depends(authenticated),
):
    file_path = get_repodata_file(channel=channel_name, arch=arch)
    with NamedTemporaryFile() as tmp_file:
        while content := await file.read(1024):
            tmp_file.write(content)
        # Rename atomically to prevent any new reads from getting a partial file
        # There's still a race condition when two POST requests come through at the same time,
        # However this falls under the category of "don't do that it hurts"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_file.name).replace(file_path)

@app.post("/wheels")
async def set_wheel_index(
    file: UploadFile = File(...),
    _authenticated: HTTPBasicCredentials = Depends(authenticated),
):
    global wheel_url_cache
    file_path = get_wheel_cache_path()
    with NamedTemporaryFile() as tmp_file:
        while content := await file.read(1024):
            tmp_file.write(content)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_file.name).replace(file_path)
        wheel_url_cache = None

def get_wheel_cache_path() -> Path:
    base_path = os.environ.get("REPO_PATH")
    base_path = Path(base_path) if base_path else Path(__file__).parent
    return base_path / "wheel_cache.json"

def get_wheel_url_cache() -> dict[str, str]:
    global wheel_url_cache
    if wheel_url_cache is None:
        file = get_wheel_cache_path()
        try:
            with file.open() as f:
                wheel_url_cache = json.load(f)
        except Exception:
            raise HTTPException(status_code=500, detail="Wheel cache file not found")
    if not wheel_url_cache:
        raise HTTPException(status_code=500, detail="Index file not found")
    return wheel_url_cache

def get_repodata_file(*, channel: str, arch: str) -> Path:
    if not valid_channel_name.match(channel):
        raise HTTPException(status_code=400, detail="Invalid channel name")
    
    if channel.lower() == "wheel_cache":
        raise HTTPException(status_code=400, detail="Invalid channel name")

    valid_arch = ["noarch", "osx-arm64", "osx-64", "linux-64", "win-64"]
    if arch not in valid_arch:
        raise HTTPException(status_code=400, detail="Invalid arch name")
    base_path = os.environ.get("REPO_PATH")
    base_path = Path(base_path) if base_path else Path(__file__).parent / "repodata"
    return base_path / arch / f"{channel}.json"
