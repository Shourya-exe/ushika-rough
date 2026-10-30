"""Download inbound media from the Cloud API into local storage (Django's default storage).

Flow: GET /{media_id} for a short-lived URL (valid ~5 minutes) and metadata,
then stream the file with the same bearer token, enforcing a size limit and
checking the SHA-256 Meta reported before the file is saved.
"""

import base64
import binascii
import hashlib
import logging
import mimetypes
import re
import tempfile
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files import File
from django.utils import timezone
from django.utils.text import get_valid_filename

from .client import WhatsAppAPIError, WhatsAppClient
from .models import MediaAttachment

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024

# WhatsApp types that mimetypes misses or names oddly (stickers are webp, voice notes ogg/opus).
PREFERRED_EXTENSIONS = {"image/jpeg": ".jpg", "image/webp": ".webp", "audio/ogg": ".ogg", "audio/opus": ".opus"}

# What a browser may show inline. Previews come from the app's own origin to a logged-in user, so
# never add a type that can carry scripts (HTML, SVG, XML): those files can only be downloaded.
PREVIEW_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/webm",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/opus",
    "audio/wav",
}


class MediaDownloadError(Exception):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class DownloadOutcome:
    ok: bool
    retryable: bool = False
    error: str = ""


def media_kind(attachment: MediaAttachment) -> str:
    """"image", "pdf", or "other" (audio, video, stickers and non-PDF documents)."""
    if attachment.media_type == "image":
        return "image"
    if attachment.media_type == "document" and attachment.mime_type.split(";")[0].strip().lower() == "application/pdf":
        return "pdf"
    return "other"


def save_refusal(attachment: MediaAttachment, *, admin: bool) -> str:
    """Why this attachment's file may not be saved, or "" when it may.

    Images and PDFs follow the sender's ContactLevel, for admins too. Every other
    kind of media can only be saved by an admin.
    """
    kind = media_kind(attachment)
    if kind == "other":
        label = "non-PDF documents" if attachment.media_type == "document" else f"{attachment.media_type} files"
        return "" if admin else f"Only admins can save {label}."
    level = attachment.message.contact.level
    if kind == "image" and not (level and level.can_save_images):
        return "This contact's level does not allow saving images."
    if kind == "pdf" and not (level and level.can_save_pdfs):
        return "This contact's level does not allow saving PDFs."
    return ""


def preview_mime_type(attachment: MediaAttachment) -> str:
    """The attachment's MIME type without parameters if a browser may show it inline, otherwise ""."""
    mime_type = attachment.mime_type.split(";")[0].strip().lower()
    return mime_type if mime_type in PREVIEW_MIME_TYPES else ""


def fetch_unsaved(attachment: MediaAttachment, client: WhatsAppClient | None = None):
    """Fetch a file from WhatsApp with the usual checks, without saving it or changing the attachment.

    Returns a temp file, deleted when closed, and its MIME type. Raises MediaDownloadError.
    """
    client = client or WhatsAppClient()
    tmp = tempfile.TemporaryFile()
    try:
        mime_type, _ = _fetch(attachment, client, tmp)
    except (WhatsAppAPIError, MediaDownloadError, requests.RequestException, OSError) as exc:
        tmp.close()
        logger.warning("Media %s unsaved fetch failed: %s", attachment.media_id, exc)
        raise MediaDownloadError(str(exc)) from exc
    tmp.seek(0)
    return tmp, mime_type


def download_attachment(attachment: MediaAttachment, client: WhatsAppClient | None = None) -> DownloadOutcome:
    """Download one attachment. The result is always recorded on the attachment; nothing is raised."""
    if attachment.download_status == MediaAttachment.DownloadStatus.DOWNLOADED and attachment.file:
        return DownloadOutcome(ok=True)

    client = client or WhatsAppClient()
    attachment.download_attempts += 1
    try:
        _download(attachment, client)
    except (WhatsAppAPIError, MediaDownloadError) as exc:
        outcome = DownloadOutcome(ok=False, retryable=exc.retryable, error=str(exc))
    except (requests.RequestException, OSError) as exc:
        outcome = DownloadOutcome(ok=False, retryable=True, error=f"{type(exc).__name__}: {exc}")
    else:
        outcome = DownloadOutcome(ok=True)

    if outcome.ok:
        attachment.download_status = MediaAttachment.DownloadStatus.DOWNLOADED
        attachment.downloaded_at = timezone.now()
        attachment.last_error = ""
        logger.info("Downloaded media %s to %s", attachment.media_id, attachment.file.name)
    else:
        attachment.download_status = MediaAttachment.DownloadStatus.FAILED
        attachment.last_error = outcome.error
        logger.warning(
            "Media %s download failed (attempt %s, retryable=%s): %s",
            attachment.media_id,
            attachment.download_attempts,
            outcome.retryable,
            outcome.error,
        )
    attachment.save()
    return outcome


def _download(attachment: MediaAttachment, client: WhatsAppClient) -> None:
    with tempfile.TemporaryFile() as tmp:
        mime_type, size = _fetch(attachment, client, tmp)
        tmp.seek(0)
        django_file = File(tmp, name=safe_filename(attachment, mime_type))
        django_file.size = size
        attachment.file.save(django_file.name, django_file, save=False)

    attachment.mime_type = mime_type
    attachment.file_size = size


def _fetch(attachment: MediaAttachment, client: WhatsAppClient, out) -> tuple[str, int]:
    """Stream the file into `out`, enforcing the size limit, HTML check and hash. Returns (mime_type, size)."""
    max_bytes = settings.WHATSAPP["MEDIA_MAX_BYTES"]
    info = client.get_media_info(attachment.media_id)
    url = info.get("url")
    if not url:
        raise MediaDownloadError("Media lookup returned no download URL")

    mime_type = info.get("mime_type") or attachment.mime_type
    expected_sha256 = info.get("sha256") or attachment.sha256
    declared_size = _as_int(info.get("file_size"))
    if declared_size and declared_size > max_bytes:
        raise MediaDownloadError(f"File is {declared_size} bytes; the limit is {max_bytes}")

    response = client.open_media_stream(url)
    try:
        content_type = response.headers.get("Content-Type", "")
        if content_type.startswith("text/html") and not mime_type.startswith("text/html"):
            # Meta answers expired or unauthorised media URLs with an HTML error page.
            raise MediaDownloadError("Got an HTML page instead of the media file", retryable=True)
        size, digest = _copy_limited(response, out, max_bytes)
    finally:
        response.close()

    if expected_sha256 and _sha256_matches(expected_sha256, digest) is False:
        raise MediaDownloadError("SHA-256 of the downloaded file does not match WhatsApp's", retryable=True)
    return mime_type, size


def _copy_limited(response, out, max_bytes: int) -> tuple[int, bytes]:
    hasher = hashlib.sha256()
    size = 0
    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
        if not chunk:
            continue
        size += len(chunk)
        if size > max_bytes:
            raise MediaDownloadError(f"File exceeds the {max_bytes}-byte limit")
        hasher.update(chunk)
        out.write(chunk)
    if size == 0:
        raise MediaDownloadError("Downloaded file is empty", retryable=True)
    return size, hasher.digest()


def _sha256_matches(expected: str, digest: bytes) -> bool | None:
    """Compare against a hex or base64 SHA-256. None when the format is not recognised."""
    expected = expected.strip()
    if re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        return expected.lower() == digest.hex()
    try:
        normalized = expected.replace("-", "+").replace("_", "/")
        decoded = base64.b64decode(normalized + "=" * (-len(normalized) % 4), validate=True)
    except (binascii.Error, ValueError):
        decoded = b""
    if len(decoded) == 32:
        return decoded == digest
    logger.warning("Unrecognised sha256 format %r; skipping integrity check", expected[:16])
    return None


def safe_filename(attachment: MediaAttachment, mime_type: str) -> str:
    """The sender's filename made filesystem-safe, or `<type>_<media_id><ext>` when there is none."""
    base_type = mime_type.split(";")[0].strip().lower()
    extension = PREFERRED_EXTENSIONS.get(base_type) or (mimetypes.guess_extension(base_type) if base_type else None)
    name = ""
    if attachment.filename:
        try:
            name = get_valid_filename(attachment.filename.replace("\\", "/").rsplit("/", 1)[-1])
        except SuspiciousFileOperation:
            name = ""
    if not name:
        name = get_valid_filename(f"{attachment.media_type}_{attachment.media_id}")
    if extension and "." not in name:
        name += extension
    return name[-150:]


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
