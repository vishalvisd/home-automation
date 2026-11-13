from fastapi import HTTPException, status

from visdcam_downloader.services.b2_client import B2NotConfiguredError
from visdcam_downloader.services.ffmpeg_tools import FfmpegNotFoundError


def http_error(error: Exception) -> HTTPException:
    """Turn a service error into a readable HTTP error for the UI."""

    if isinstance(error, (B2NotConfiguredError, FfmpegNotFoundError, ValueError)):
        return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(error))

    if isinstance(error, FileNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(error))

    name = type(error).__name__
    message = str(error) or name

    if "Unauthorized" in name or "unauthorized" in message.lower():
        message = "Backblaze rejected the key ID or application key"
    elif "NonExistentBucket" in name or "bucket" in message.lower() and "not" in message.lower():
        message = f"Backblaze bucket problem: {message}"

    return HTTPException(status.HTTP_502_BAD_GATEWAY, detail=message)
