"""
Files API Routes
Handles file upload and download operations
"""

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

from settings import settings


router = APIRouter()

# In-memory file registry (in production, use a database)
_file_registry: dict = {}


class UploadTooLargeError(Exception):
    pass


def _write_upload_file(
    source_file, destination: Path, *, max_size: int, chunk_size: int = 1024 * 1024
) -> int:
    bytes_written = 0
    with open(destination, "wb") as buffer:
        while True:
            chunk = source_file.read(chunk_size)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > max_size:
                raise UploadTooLargeError()
            buffer.write(chunk)
    return bytes_written


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file (PDF, markdown, etc.)"""
    # Validate file type
    allowed_types = {".pdf", ".md", ".txt", ".markdown"}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{file_ext}' not allowed. Allowed: "
                f"{', '.join(sorted(allowed_types))}"
            ),
        )

    # Generate unique file ID
    file_id = str(uuid.uuid4())
    safe_filename = f"{file_id}{file_ext}"
    file_path = Path(settings.upload_dir) / safe_filename

    bytes_written = 0
    try:
        # Ensure upload directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Save file
        try:
            bytes_written = await asyncio.to_thread(
                _write_upload_file,
                file.file,
                file_path,
                max_size=settings.max_upload_size,
            )
        except UploadTooLargeError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "File size exceeds limit of "
                    f"{settings.max_upload_size // (1024 * 1024)}MB"
                ),
            ) from exc

        # Register file
        _file_registry[file_id] = {
            "id": file_id,
            "original_name": file.filename,
            "path": str(file_path),
            "size": bytes_written,
            "type": file_ext,
        }

        return {
            "file_id": file_id,
            "filename": file.filename,
            "path": str(file_path),
            "size": bytes_written,
        }

    except HTTPException:
        file_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload file: {str(e)}",
        )
    finally:
        await file.close()


@router.get("/download/{file_id}")
async def download_file(file_id: str):
    """Download a file by ID"""
    file_info = _file_registry.get(file_id)

    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = Path(file_info["path"])

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists")

    return FileResponse(
        path=str(file_path),
        filename=file_info["original_name"],
        media_type="application/octet-stream",
    )


@router.delete("/delete/{file_id}")
async def delete_file(file_id: str):
    """Delete an uploaded file"""
    file_info = _file_registry.get(file_id)

    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = Path(file_info["path"])

    try:
        if file_path.exists():
            file_path.unlink()

        del _file_registry[file_id]

        return {"status": "deleted", "file_id": file_id}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete file: {str(e)}",
        )


@router.get("/info/{file_id}")
async def get_file_info(file_id: str):
    """Get information about an uploaded file"""
    file_info = _file_registry.get(file_id)

    if not file_info:
        raise HTTPException(status_code=404, detail="File not found")

    return file_info
