from fastapi import FastAPI, Depends
import re
from fastapi.responses import FileResponse, RedirectResponse
from fastapi import HTTPException, File, UploadFile
from pathlib import Path
from tempfile import NamedTemporaryFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import os
import secrets

app = FastAPI()
valid_channel_name = re.compile(
    "^[a-z0-9_]+$"
)  # Notably don't allow any ./ or anything that could cause a directory traversal
security = HTTPBasic()


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
    file_path = get_repodata_path(channel=channel_name, arch=arch)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


@app.get("/channels/{channel_name}/{arch}/{filename}.whl")
async def get_wheel(filename: str):
    filename = f"{filename}.whl"  # Re-append the wheel extension
    try:
        url = whl_pypi_url(filename)
        return RedirectResponse(url)
    except Exception:
        raise HTTPException(status_code=404, detail="whl cannot be redirected")


@app.get("/channels/{channel_name}/{arch}/{filename}.tar.bz2")
async def get_tarball(filename: str):
    if not filename.startswith("_c"):
        raise HTTPException(status_code=404, detail="File not found")
    path = get_metapackage_stub_path()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.post("/channels/{channel_name}/{arch}/repodata.json")
async def set_repodata(
    channel_name: str,
    arch: str,
    file: UploadFile = File(...),
    _authenticated: HTTPBasicCredentials = Depends(authenticated),
):
    file_path = get_repodata_path(channel=channel_name, arch=arch)
    with NamedTemporaryFile() as tmp_file:
        while content := await file.read(1024):
            tmp_file.write(content)
        # Rename atomically to prevent any new reads from getting a partial file
        # There's still a race condition when two POST requests come through at the same time,
        # However this falls under the category of "don't do that it hurts"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        Path(tmp_file.name).replace(file_path)


def get_repodata_path(*, channel: str, arch: str) -> Path:
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


def get_metapackage_stub_path() -> Path:
    return Path(__file__).parent / "metapackagestub-1.0-0.tar.bz2"


def whl_pypi_url(filename):
    # https://packaging.python.org/en/latest/specifications/binary-distribution-format/#binary-distribution-format
    # could also contain build_tag but not allowed on PyPI
    raw_name, _, python_tag = filename.split("-")[:3]
    # PEP 503
    name = re.sub(r"[-_.]+", "-", raw_name).lower()
    host = "https://files.pythonhosted.org"
    return f"{host}/packages/{python_tag}/{name[0]}/{name}/{filename}"
