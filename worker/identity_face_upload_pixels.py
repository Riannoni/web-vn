"""CPU-only face-upload pixel provenance for the installed SDXL/Pony sprite path.

Compares actual canonical source image pixels to the Comfy upload produced
by the installed worker: RGB -> ImageOps.fit(512, 512, LANCZOS) -> PNG.

This does NOT authenticate the source ledger/signature, model weights,
actual IPAdapter conditioning or rendered identity. Only a separately
trusted creation-time producer can supply frozen actor/asset/outfit values.
No GPU/API calls or private image disclosure.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import re

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

HEX64 = re.compile(r"^[a-f0-9]{64}$")
ASSET = re.compile(
    r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\.(?:png|jpe?g|webp)$",
    re.IGNORECASE,
)


class FaceUploadBlocked(ValueError):
    """Unsafe, stale or unbound canonical face input."""


def _digest(value, expected, label, limit):
    if not isinstance(value, bytes) or not 0 < len(value) <= limit:
        raise FaceUploadBlocked(label + "_bytes_missing_or_oversize")
    if not isinstance(expected, str) or not HEX64.fullmatch(expected):
        raise FaceUploadBlocked(label + "_sha_invalid")
    if sha256(value).hexdigest() != expected:
        raise FaceUploadBlocked(label + "_sha_mismatch")


def _pixels(raw, *, source):
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise FaceUploadBlocked("unsafe_pillow_truncated_image_policy")
    allowed = {"PNG", "JPEG", "WEBP"} if source else {"PNG"}
    try:
        with Image.open(BytesIO(raw)) as img:
            if (img.format not in allowed or getattr(img, "n_frames", 1) != 1
                    or not (1 <= img.width <= 4096 and 1 <= img.height <= 4096)
                    or img.width * img.height > 16_777_216):
                raise FaceUploadBlocked("face_image_format_or_dimensions_invalid")
            fmt = img.format
            img.verify()
        with Image.open(BytesIO(raw)) as img:
            if img.format != fmt:
                raise FaceUploadBlocked("face_image_changed_during_decode")
            img.load()
            return img.copy()
    except (OSError, SyntaxError, ValueError, UnidentifiedImageError,
            Image.DecompressionBombError) as exc:
        if isinstance(exc, FaceUploadBlocked):
            raise
        raise FaceUploadBlocked("face_image_pixels_undecodable") from exc


def _nonblank(value, *, limit):
    return (isinstance(value, str) and value.strip() == value
            and 0 < len(value) <= limit and bool(value.strip()))


def verify_sprite_face_upload(
    *, canonical_bytes, uploaded_bytes, canonical_sha256, uploaded_sha256,
    actor_id, frozen_actor_id, face_asset, frozen_face_asset,
    current_outfit, frozen_outfit,
):
    """Fail closed on a substituted transformed upload; not on metadata alone.

    Frozen actor/asset/outfit and source SHA must come from a separate trusted
    source/creation-time receipt. Matching user-supplied strings are not
    authentication. Renderer must invoke with actual original and Comfy bytes.
    """
    if not (_nonblank(actor_id, limit=100)
            and _nonblank(frozen_actor_id, limit=100)
            and actor_id == frozen_actor_id):
        raise FaceUploadBlocked("canonical_actor_attribution_mismatch")
    if not (isinstance(face_asset, str)
            and ASSET.fullmatch(face_asset)
            and face_asset == frozen_face_asset):
        raise FaceUploadBlocked("canonical_face_asset_attribution_mismatch")
    if not (_nonblank(current_outfit, limit=320)
            and current_outfit.casefold() not in ("unknown", "default", "unspecified")
            and current_outfit == frozen_outfit):
        raise FaceUploadBlocked("canonical_current_outfit_mismatch")

    _digest(canonical_bytes, canonical_sha256, "canonical_face", 35_000_000)
    _digest(uploaded_bytes, uploaded_sha256, "comfy_face_upload", 12_000_000)
    canonical = _pixels(canonical_bytes, source=True)
    uploaded = _pixels(uploaded_bytes, source=False)

    # A byte-authentic but empty reference has no visible face to condition.
    # This is only a necessary CPU sanity check: it cannot establish actual
    # facial content, origin authentication, wardrobe or visual G2.
    if ("A" in canonical.getbands() or "transparency" in canonical.info):
        # Installed worker discards alpha with .convert("RGB") rather than
        # compositing it against an authenticated, frozen background. As a
        # result, even one translucent pixel can feed hidden RGB into the
        # Face-IPAdapter image. Until an independently reviewed transparent
        # source normalization is deployed, reject *all* nonopaque source
        # alpha; valid fully opaque RGBA and RGB sources remain supported.
        alpha_low, alpha_high = canonical.convert("RGBA").getchannel("A").getextrema()
        if alpha_high == 0:
            raise FaceUploadBlocked("canonical_face_reference_invisible")
        if alpha_low < 255:
            raise FaceUploadBlocked("canonical_face_reference_transparency_unsupported")
    canonical_rgb = canonical.convert("RGB")
    if all(low == high for low, high in canonical_rgb.getextrema()):
        raise FaceUploadBlocked("canonical_face_reference_blank")

    # Mirrors installed worker.py SHA a865c4a9...: fetch_asset(...).convert("RGB"),
    # ImageOps.fit(..., (512,512), LANCZOS), pil_png(..., optimize=True).
    # Compare decoded pixels, not PNG compression bytes.
    expected = ImageOps.fit(
        canonical_rgb, (512, 512),
        method=Image.Resampling.LANCZOS,
    )
    # PNG tRNS can preserve PIL mode RGB while assigning alpha=0 to an RGB
    # color. The Comfy consumer expects an actually opaque RGB image, not
    # merely a mode string and byte-identical hidden RGB samples. Reject
    # tRNS even when the transparency key does not occur in the pixels.
    if (uploaded.mode != "RGB" or uploaded.size != (512, 512)
            or "transparency" in uploaded.info):
        raise FaceUploadBlocked("canonical_face_upload_mode_or_canvas_changed")
    if uploaded.tobytes() != expected.tobytes():
        raise FaceUploadBlocked("canonical_face_upload_pixels_do_not_match")

    return {
        "status": "FACE_UPLOAD_PIXELS_MATCH_NOT_G2",
        "actor_id": actor_id,
        "face_asset": face_asset,
        "canonical_sha256": canonical_sha256,
        "upload_sha256": uploaded_sha256,
        "transform": "RGB_fit_512_LANCZOS",
        "origin_authenticated": False,
        "wardrobe_pixels_verified": False,
        "g2_verified": False,
        "publish_eligible": False,
    }
