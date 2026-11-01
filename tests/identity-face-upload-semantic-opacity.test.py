"""One-factor synthetic CPU regression: Comfy upload PNG transparency metadata.

An RGB PNG with tRNS still has PIL mode RGB, but can contain semantically
transparent pixels. A SHA and RGB pixel comparison alone must not admit it.
"""
import hashlib
import io
import sys
import unittest
from pathlib import Path
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from identity_face_upload_pixels import FaceUploadBlocked, verify_sprite_face_upload

ACTOR = "synthetic_actor_1"
FACE = "12345678-1234-1234-1234-123456789abc.png"
OUTFIT = "closed blue jacket"


def png(image, **kwargs):
    b = io.BytesIO()
    image.save(b, format="PNG", **kwargs)
    return b.getvalue()


def fixture():
    source = Image.new("RGB", (640, 800), (20, 100, 170))
    for x in range(85, 380):
        for y in range(45, 240):
            source.putpixel((x, y), (215, 160, 75))
    original = png(source)
    fitted = ImageOps.fit(source, (512, 512), method=Image.Resampling.LANCZOS)
    return original, fitted


def preflight(original, uploaded):
    return verify_sprite_face_upload(
        canonical_bytes=original,
        uploaded_bytes=uploaded,
        canonical_sha256=hashlib.sha256(original).hexdigest(),
        uploaded_sha256=hashlib.sha256(uploaded).hexdigest(),
        actor_id=ACTOR,
        frozen_actor_id=ACTOR,
        face_asset=FACE,
        frozen_face_asset=FACE,
        current_outfit=OUTFIT,
        frozen_outfit=OUTFIT,
    )


class SemanticOpacityTests(unittest.TestCase):
    def test_plain_rgb_upload_still_passes(self):
        original, fitted = fixture()
        verdict = preflight(original, png(fitted))
        self.assertEqual(verdict["status"], "FACE_UPLOAD_PIXELS_MATCH_NOT_G2")

    def test_rgb_trns_matching_pixel_is_rejected(self):
        original, fitted = fixture()
        transparent_color = fitted.getpixel((0, 0))
        upload = png(fitted, transparency=transparent_color)
        with Image.open(io.BytesIO(upload)) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertIn("transparency", image.info)
            self.assertEqual(image.convert("RGBA").getpixel((0, 0))[3], 0)
        with self.assertRaisesRegex(FaceUploadBlocked, "mode|transparency"):
            preflight(original, upload)

    def test_rgb_trns_unused_marker_still_rejected(self):
        original, fitted = fixture()
        upload = png(fitted, transparency=(0, 1, 2))
        with Image.open(io.BytesIO(upload)) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertIn("transparency", image.info)
            self.assertEqual(image.convert("RGBA").getchannel("A").getextrema(), (255, 255))
        with self.assertRaisesRegex(FaceUploadBlocked, "mode|transparency"):
            preflight(original, upload)


if __name__ == "__main__":
    unittest.main()
