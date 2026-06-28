from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile


UPLOAD_DIR = Path("uploads")


async def save_attachment(attachment: UploadFile | None) -> tuple[str | None, str | None]:
    if not attachment or not attachment.filename:
        return None, None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(attachment.filename).suffix
    stored_name = f"{uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(await attachment.read())
    return attachment.filename, str(stored_path)
