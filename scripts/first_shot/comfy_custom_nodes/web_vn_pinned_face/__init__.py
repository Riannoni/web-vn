"""CPU-first, content-embedded Comfy face input. Source-only until Lab installs.

The graph carries the actual PNG bytes, not a mutable LoadImage filename.
This is transport integrity, NOT canonical source-origin authentication or G2.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re

from PIL import Image, ImageFile

MAX_PNG_BYTES = 12_000_000
MAX_B64_CHARS = 4 * ((MAX_PNG_BYTES + 2) // 3)
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def decode_pinned_face_png(png_base64: str, sha256: str):
    """Return fully decoded 512x512 RGB PIL image from hash-bound graph bytes."""
    if not isinstance(sha256, str) or SHA256.fullmatch(sha256) is None:
        raise ValueError("pinned_face_invalid_sha")
    if not isinstance(png_base64, str) or len(png_base64) > MAX_B64_CHARS:
        raise ValueError("pinned_face_invalid_transport_size")
    try:
        raw = base64.b64decode(png_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("pinned_face_invalid_base64") from exc
    if not raw or len(raw) > MAX_PNG_BYTES:
        raise ValueError("pinned_face_invalid_transport_size")
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("pinned_face_sha_mismatch")
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or ImageFile.LOAD_TRUNCATED_IMAGES:
        raise ValueError("pinned_face_invalid_png")
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.format != "PNG" or original.size != (512, 512):
                raise ValueError("pinned_face_invalid_canvas")
            original.verify()
        with Image.open(io.BytesIO(raw)) as original:
            original.load()
            return original.convert("RGB")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("pinned_face_invalid_png_pixels") from exc


def encode_pinned_face_png(raw: bytes, sha256: str) -> str:
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError("pinned_face_sha_mismatch")
    blob = base64.b64encode(raw).decode("ascii")
    decode_pinned_face_png(blob, sha256)
    return blob


class WebVNPinnedFacePNG:
    """Comfy IMAGE node: runtime uses signed-off bytes embedded in prompt graph."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "png_base64": ("STRING", {"multiline": True}),
            "sha256": ("STRING", {"multiline": False}),
        }}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "load"
    CATEGORY = "web-vn/verified-inputs"

    def load(self, png_base64, sha256):
        import numpy as np
        import torch
        image = decode_pinned_face_png(png_base64, sha256)
        rgb = np.asarray(image, dtype=np.float32) / 255.0
        return (torch.from_numpy(rgb).unsqueeze(0),)


NODE_CLASS_MAPPINGS = {"WebVNPinnedFacePNG": WebVNPinnedFacePNG}
NODE_DISPLAY_NAME_MAPPINGS = {"WebVNPinnedFacePNG": "web-vn pinned face PNG"}
