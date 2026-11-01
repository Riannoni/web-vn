"""SHA-only Comfy face input backed by a private content-addressed store.

Comfy prompt/history carries only SHA-256, never base64 face bytes or a path.
Requires a private out-of-band store mount configured by GPU Lab; source
transport integrity is NOT canonical origin authentication or G2.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re

from PIL import Image, ImageFile
from .sha_store import read_pinned_store

MAX_PNG_BYTES = 12_000_000
MAX_B64_CHARS = 4 * ((MAX_PNG_BYTES + 2) // 3)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class _PinnedFaceInvalidMode(ValueError):
    """A hash-valid PNG whose pixel mode is not an admitted canonical RGB face."""


def _decode_pinned_face_bytes(raw: bytes, sha256: str):
    if not isinstance(sha256, str) or SHA256.fullmatch(sha256) is None:
        raise ValueError("pinned_face_invalid_sha")
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_PNG_BYTES:
        raise ValueError("pinned_face_invalid_transport_size")
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("pinned_face_sha_mismatch")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError("pinned_face_invalid_png")
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.format != "PNG" or original.size != (512, 512):
                raise ValueError("pinned_face_invalid_canvas")
            if original.mode != "RGB":
                raise _PinnedFaceInvalidMode("pinned_face_invalid_mode")
            original.verify()
        with Image.open(io.BytesIO(raw)) as original:
            if original.mode != "RGB":
                raise _PinnedFaceInvalidMode("pinned_face_invalid_mode")
            original.load()
            return original.copy()
    except _PinnedFaceInvalidMode:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("pinned_face_invalid_png_pixels") from exc


def decode_pinned_face_png(png_base64: str, sha256: str):
    """CPU-only legacy transport verifier; NEVER a Comfy graph node input."""
    if not isinstance(png_base64, str) or len(png_base64) > MAX_B64_CHARS:
        raise ValueError("pinned_face_invalid_transport_size")
    try:
        raw = base64.b64decode(png_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("pinned_face_invalid_base64") from exc
    return _decode_pinned_face_bytes(raw, sha256)


def decode_pinned_face_from_store(sha256: str, *, root=None):
    """Only untrusted graph input is SHA; root comes from trusted config."""
    return _decode_pinned_face_bytes(read_pinned_store(sha256, root=root), sha256)


def encode_pinned_face_png(raw: bytes, sha256: str) -> str:
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("pinned_face_sha_mismatch")
    blob = base64.b64encode(raw).decode("ascii")
    decode_pinned_face_png(blob, sha256)
    return blob


class WebVNPinnedFacePNG:
    """Comfy IMAGE: runtime reads exact bytes from a private store by SHA."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "sha256": ("STRING", {"multiline": False}),
        }}

    @classmethod
    def VALIDATE_INPUTS(cls, sha256):
        # Comfy preflight must reject missing/mismatched private bytes before
        # GPU execution. Recheck again in load() to close post-validation races.
        try:
            decode_pinned_face_from_store(sha256)
            return True
        except (OSError, ValueError):
            return "pinned_face_runtime_source_not_verified"

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "load"
    CATEGORY = "web-vn/verified-inputs"

    def load(self, sha256):
        import numpy as np
        import torch
        image = decode_pinned_face_from_store(sha256)
        rgb = np.asarray(image, dtype=np.float32) / 255.0
        return (torch.from_numpy(rgb).unsqueeze(0),)


NODE_CLASS_MAPPINGS = {"WebVNPinnedFacePNG": WebVNPinnedFacePNG}
NODE_DISPLAY_NAME_MAPPINGS = {"WebVNPinnedFacePNG": "web-vn pinned face PNG"}
