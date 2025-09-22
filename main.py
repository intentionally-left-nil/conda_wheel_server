import hashlib
import logging
import os
import re
import secrets
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
valid_channel_name = re.compile(
    "^[a-z0-9_]+$"
)  # Notably don't allow any ./ or anything that could cause a directory traversal

valid_short_hash = re.compile("^[a-f0-9]{8}$")
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


@app.get("/psm/channels/{channel_name}/{arch}/repodata.json")
@app.get("/psm/channels/{channel_name}/{subchannel}/{arch}/repodata.json")
@app.get("/channels/{channel_name}/{arch}/repodata.json")
async def get_repodata(channel_name: str, arch: str, subchannel: str | None = None):
    file_path = get_repodata_path(
        channel=channel_name, subchannel=subchannel, arch=arch
    )
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(file_path)


@app.get("/psm/channels/{channel_name}/{arch}/{filename}.whl")
@app.get("/psm/channels/{channel_name}/{subchannel}/{arch}/{filename}.whl")
@app.get("/channels/{channel_name}/{arch}/{filename}.whl")
async def get_wheel(
    request: Request, channel_name: str, filename: str, subchannel: str | None = None
):
    filename = f"{filename}.whl"  # Re-append the wheel extension
    if request.url.path.startswith("/psm"):
        psm_uri = os.environ.get("PSM_URI")
        if not psm_uri:
            raise HTTPException(
                status_code=500, detail="Server not configured correctly"
            )
    try:
        if request.url.path.startswith("/psm"):
            url = whl_psm_uri(channel_name, subchannel, filename)
        else:
            url = whl_pypi_url(filename)
        return RedirectResponse(url)
    except Exception as e:
        print(e)
        raise HTTPException(status_code=404, detail="whl cannot be redirected")


@app.get("/psm/channels/{channel_name}/{arch}/{filename}.tar.bz2")
@app.get("/psm/channels/{channel_name}/{subchannel}/{arch}/{filename}.tar.bz2")
@app.get("/channels/{channel_name}/{arch}/{filename}.tar.bz2")
async def get_tarball(filename: str):
    if not filename.startswith("_c"):
        raise HTTPException(status_code=404, detail="Invalid filename")
    hash = filename.split("_")[-1]
    if not valid_short_hash.match(hash):
        raise HTTPException(status_code=404, detail=f"Invalid hash: {hash}")
    stub_path = get_stubs_path() / f"{hash}.tar.bz2"
    if not stub_path.exists():
        raise HTTPException(status_code=404, detail=f"Hash {hash} not found")
    if not stub_path.is_file():
        raise HTTPException(status_code=404, detail="Invalid stub")
    return FileResponse(stub_path)


@app.post("/psm/channels/{channel_name}/{arch}/repodata.json")
@app.post("/psm/channels/{channel_name}/{subchannel}/{arch}/repodata.json")
@app.post("/channels/{channel_name}/{arch}/repodata.json")
async def set_repodata(
    channel_name: str,
    arch: str,
    file: UploadFile = File(...),
    _authenticated: HTTPBasicCredentials = Depends(authenticated),
    subchannel: str | None = None,
):
    file_path = get_repodata_path(
        channel=channel_name, subchannel=subchannel, arch=arch
    )
    file_path.parent.mkdir(parents=True, exist_ok=True)
    # Prevent cross-device link errors by creating a temporary file in the
    # same directory as the final destination
    with NamedTemporaryFile(dir=file_path.parent.parent, suffix=".tmp") as tmp_file:
        while content := await file.read(1024):
            tmp_file.write(content)
        tmp_file.flush()
        # Rename atomically to prevent any new reads from getting a partial file
        # There's still a race condition when two POST requests come through at the same time,
        # However this falls under the category of "don't do that it hurts"
        Path(tmp_file.name).replace(file_path)


@app.delete("/psm/channels/{channel}")
@app.delete("/psm/channels/{channel}/{subchannel}")
@app.delete("/channels/{channel}")
async def delete_channel(
    channel: str,
    _authenticated: HTTPBasicCredentials = Depends(authenticated),
    subchannel: str | None = None,
):
    channel_path = get_channel_path(channel, subchannel)
    try:
        shutil.rmtree(channel_path)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete channel: {str(e)}"
        )


@app.post("/stubs")
async def add_stub(
    file: UploadFile = File(...),
    _authenticated: HTTPBasicCredentials = Depends(authenticated),
):
    stubs_path = get_stubs_path()
    stubs_path.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=stubs_path, suffix=".tmp") as tmp_file:
        while content := await file.read(1024):
            tmp_file.write(content)
        tmp_file.flush()
        dest_name = get_short_hash(Path(tmp_file.name)) + ".tar.bz2"
        Path(tmp_file.name).replace(stubs_path / dest_name)
        logger.info(f"Added stub: {(stubs_path / dest_name).resolve()}")

    return {"hash": dest_name.removesuffix(".tar.bz2")}


@app.get("/stubs")
async def get_stubs():
    stubs_path = get_stubs_path()
    stubs_path.mkdir(parents=True, exist_ok=True)
    stubs = [
        x.name.removesuffix(".tar.bz2") for x in stubs_path.iterdir() if x.is_file()
    ]
    return {"stubs": stubs}


def get_base_path():
    base_path = os.environ.get("REPO_PATH")
    base_path = Path(base_path) if base_path else Path(__file__).parent / "repodata"
    return base_path


def get_repodata_path(*, channel: str, subchannel: str | None, arch: str) -> Path:
    valid_arch = ["noarch", "osx-arm64", "osx-64", "linux-64", "win-64"]
    if arch not in valid_arch:
        raise HTTPException(status_code=400, detail="Invalid arch name")
    channel_path = get_channel_path(channel, subchannel)
    return channel_path / arch / f"{channel}.json"


def get_channel_path(channel: str, subchannel: str | None) -> Path:
    if not valid_channel_name.match(channel) or (
        subchannel and not valid_channel_name.match(subchannel)
    ):
        raise HTTPException(status_code=400, detail="Invalid channel name")
    path = get_base_path() / "channels" / channel
    if subchannel:
        path = path / subchannel
    return path


def get_stubs_path() -> Path:
    return get_base_path() / "stubs"


def get_metapackage_stub_path() -> Path:
    return Path(__file__).parent / "metapackagestub-1.0-0.tar.bz2"


def get_short_hash(filename: Path) -> str:
    return hashlib.sha256(filename.read_bytes()).hexdigest()[:8]


def whl_pypi_url(filename: str):
    # https://packaging.python.org/en/latest/specifications/binary-distribution-format/#binary-distribution-format
    # could also contain build_tag but not allowed on PyPI
    raw_name, _, python_tag = filename.split("-")[:3]
    # PEP 503
    name = re.sub(r"[-_.]+", "-", raw_name).lower()
    host = "https://files.pythonhosted.org"
    return f"{host}/packages/{python_tag}/{name[0]}/{name}/{filename}"


def whl_psm_uri(channel: str, subchannel: str | None, filename: str):
    psm_uri = os.environ.get("PSM_URI")
    if not psm_uri:
        raise HTTPException(status_code=500, detail="Server not configured correctly")
    raw_name = filename.split("-")[0]
    name = re.sub(r"[-_.]+", "-", raw_name).lower()
    if subchannel:
        channel = f"{channel}/{subchannel}"
    return f"{psm_uri}/{channel}/simple/{name}/{filename}"
