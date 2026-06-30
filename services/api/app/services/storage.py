from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

# 单文件上传大小上限：10MB，防止恶意大文件导致 OOM
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# 分块读取大小
_CHUNK_SIZE = 64 * 1024


@dataclass(slots=True)
class StoredFile:
    file_name: str
    file_path: str
    file_url: str
    size: int


async def store_upload(upload: UploadFile, storage_root: Path, child_id: int) -> StoredFile:
    suffix = Path(upload.filename or "").suffix or ".bin"
    relative_dir = Path("children") / str(child_id)
    absolute_dir = storage_root / relative_dir
    absolute_dir.mkdir(parents=True, exist_ok=True)

    file_name = f"{uuid4().hex}{suffix}"
    absolute_path = absolute_dir / file_name

    total = 0
    with absolute_path.open("wb") as fp:
        while True:
            chunk = await upload.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                fp.close()
                absolute_path.unlink(missing_ok=True)
                raise ValueError(f"File too large, max {MAX_UPLOAD_BYTES} bytes allowed")
            fp.write(chunk)

    relative_path = (relative_dir / file_name).as_posix()
    return StoredFile(
        file_name=file_name,
        file_path=relative_path,
        file_url=f"/media/{relative_path}",
        size=total,
    )

