from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from visdcam_downloader.api.dependencies import get_settings_service, get_workflows
from visdcam_downloader.services.ffmpeg_tools import open_in_file_manager
from visdcam_downloader.services.settings_service import SettingsService
from visdcam_downloader.services.workflows import Workflows


router = APIRouter(prefix="/api/library", tags=["library"])

SettingsDependency = Annotated[SettingsService, Depends(get_settings_service)]
WorkflowsDependency = Annotated[Workflows, Depends(get_workflows)]

VIDEO_EXTENSIONS = {".mp4", ".ts", ".mov", ".mkv"}
MEDIA_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".ts": "video/mp2t", ".mkv": "video/x-matroska"}


def _allowed_roots(settings: SettingsService) -> list[Path]:
    current = settings.get()
    return [
        Path(current.output_directory).expanduser().resolve(),
        Path(current.archive_directory).expanduser().resolve(),
    ]


def _safe_path(raw: str, settings: SettingsService) -> Path:
    """Only files inside the output or archive folders may be touched."""

    path = Path(raw).expanduser().resolve()

    for root in _allowed_roots(settings):
        try:
            path.relative_to(root)
            return path
        except ValueError:
            continue

    raise HTTPException(status.HTTP_403_FORBIDDEN, "Path is outside the output folders")


class PathRequest(BaseModel):
    path: str


@router.get("")
def list_library(settings: SettingsDependency) -> dict:
    output = Path(settings.get().output_directory).expanduser()
    output.mkdir(parents=True, exist_ok=True)

    files = []
    for path in output.iterdir():
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if path.name.endswith(".part") or ".part." in path.name:
            continue
        stat = path.stat()
        files.append({
            "name": path.name,
            "path": str(path),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "extension": path.suffix.lower().lstrip("."),
            "playable": path.suffix.lower() in (".mp4", ".mov"),
        })

    files.sort(key=lambda item: item["modified"], reverse=True)
    return {"directory": str(output), "files": files}


@router.get("/file")
def serve_file(settings: SettingsDependency, path: str = Query()) -> FileResponse:
    target = _safe_path(path, settings)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return FileResponse(
        target,
        media_type=MEDIA_TYPES.get(target.suffix.lower(), "application/octet-stream"),
        filename=target.name,
    )


@router.get("/info")
def file_info(settings: SettingsDependency, workflows: WorkflowsDependency, path: str = Query()) -> dict:
    target = _safe_path(path, settings)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    tools = workflows.tools()
    if not tools.available():
        return {"path": str(target), "probe": None}
    try:
        return {"path": str(target), "probe": tools.probe(target)}
    except Exception as error:
        return {"path": str(target), "probe": None, "error": str(error)}


@router.post("/open")
def open_folder(request: PathRequest, settings: SettingsDependency) -> dict:
    target = _safe_path(request.path, settings)
    open_in_file_manager(target)
    return {"opened": str(target)}


@router.delete("")
def delete_file(settings: SettingsDependency, path: str = Query()) -> dict:
    target = _safe_path(path, settings)
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    target.unlink()
    return {"deleted": str(target)}
