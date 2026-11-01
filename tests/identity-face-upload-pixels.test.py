"""CPU-only negative tests for real canonical face -> Comfy uploaded pixels."""
import hashlib
import io
import sys
import unittest
from pathlib import Path

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from identity_face_upload_pixels import FaceUploadBlocked, verify_sprite_face_upload

ACTOR = "Actor_A"
ASSET = "12345678-1234-1234-1234-123456789abc.png"
OUTFIT = "closed buttoned blue jacket"


def png(image, *, optimize=True):
    data = io.BytesIO()
    image.save(data, "PNG", optimize=optimize)
    return data.getvalue()


def fixture():
    source = Image.new("RGBA", (640, 800), (215, 110, 70, 255))
    for x in range(100, 350):
        for y in range(30, 160):
            source.putpixel((x, y), (20, 80, 140, 255))
    original = png(source)
    fitted = ImageOps.fit(source.convert("RGB"), (512, 512),
                          method=Image.Resampling.LANCZOS)
    uploaded = png(fitted)
    return original, uploaded, fitted


def opts(original, uploaded):
    return dict(
        canonical_bytes=original,
        uploaded_bytes=uploaded,
        canonical_sha256=hashlib.sha256(original).hexdigest(),
        uploaded_sha256=hashlib.sha256(uploaded).hexdigest(),
        actor_id=ACTOR,
        frozen_actor_id=ACTOR,
        face_asset=ASSET,
        frozen_face_asset=ASSET,
        current_outfit=OUTFIT,
        frozen_outfit=OUTFIT,
    )


class FaceUploadPixelsTests(unittest.TestCase):
    def test_exact_worker_512_fit_passes_without_claiming_g2(self):
        source, upload, _ = fixture()
        result = verify_sprite_face_upload(**opts(source, upload))
        self.assertEqual(result["status"], "FACE_UPLOAD_PIXELS_MATCH_NOT_G2")
        self.assertIs(result["g2_verified"], False)
        self.assertIs(result["origin_authenticated"], False)
        self.assertIs(result["wardrobe_pixels_verified"], False)

    def test_wrong_actor_face_content_with_recomputed_upload_sha_is_rejected(self):
        source, upload, fitted = fixture()
        changed = fitted.copy()
        changed.putpixel((120, 250), (0, 0, 0))
        fake_upload = png(changed)
        with self.assertRaisesRegex(FaceUploadBlocked, "pixels"):
            verify_sprite_face_upload(**opts(source, fake_upload))

    def test_same_pixels_alternate_png_encoding_allowed(self):
        source, upload, fitted = fixture()
        alternative = png(fitted, optimize=False)
        self.assertNotEqual(upload, alternative)
        result = verify_sprite_face_upload(**opts(source, alternative))
        self.assertEqual(result["status"], "FACE_UPLOAD_PIXELS_MATCH_NOT_G2")

    def test_source_or_upload_digest_mismatch_is_blocked(self):
        source, upload, _ = fixture()
        for field in ("canonical_sha256", "uploaded_sha256"):
            with self.subTest(field=field):
                args = opts(source, upload)
                args[field] = "0" * 64
                with self.assertRaisesRegex(FaceUploadBlocked, "sha"):
                    verify_sprite_face_upload(**args)

    def test_wrong_actor_and_asset_attribution_blocked(self):
        source, upload, _ = fixture()
        for field, value in (("actor_id", "Actor_B"),
                             ("face_asset", "abcdef01-1234-1234-1234-123456789abc.png")):
            with self.subTest(field=field):
                args = opts(source, upload)
                args[field] = value
                with self.assertRaisesRegex(FaceUploadBlocked, "actor|asset"):
                    verify_sprite_face_upload(**args)

    def test_stale_or_unclosed_outfit_blocks_source_admission(self):
        source, upload, _ = fixture()
        for outfit in ("open old cape", "unknown", "", "default"):
            with self.subTest(outfit=outfit):
                args = opts(source, upload)
                args["current_outfit"] = outfit
                with self.assertRaisesRegex(FaceUploadBlocked, "outfit"):
                    verify_sprite_face_upload(**args)

    def test_missing_corrupted_or_wrong_size_upload_blocks(self):
        source, upload, fitted = fixture()
        for bad in (b"", upload[:40], png(fitted.resize((256, 256))),
                    png(fitted.convert("RGBA"))):
            with self.subTest(length=len(bad)):
                args = opts(source, bad)
                with self.assertRaises(FaceUploadBlocked):
                    verify_sprite_face_upload(**args)

    def test_blank_or_invisible_canonical_reference_is_not_admitted(self):
        # A matching transformed upload cannot create identity information
        # that was absent from the original private face reference.
        cases = (
            ("invisible_rgba", Image.new("RGBA", (640, 800), (50, 100, 150, 0))),
            ("uniform_opaque_rgb", Image.new("RGB", (640, 800), (50, 100, 150))),
        )
        for label, im in cases:
            with self.subTest(reference=label):
                original = png(im)
                fitted = ImageOps.fit(im.convert("RGB"), (512, 512),
                                      method=Image.Resampling.LANCZOS)
                upload = png(fitted)
                with self.assertRaisesRegex(FaceUploadBlocked, "invisible|blank"):
                    verify_sprite_face_upload(**opts(original, upload))

    def test_alpha_reference_with_hidden_rgb_is_not_admitted(self):
        # With the installed worker's .convert("RGB"), hidden RGB can
        # dominate the Comfy upload even when a single pixel is opaque.
        im = Image.new("RGBA", (640, 800), (12, 15, 30, 0))
        im.putpixel((10, 10), (230, 220, 170, 0))
        im.putpixel((25, 25), (80, 100, 120, 255))
        original = png(im)
        transformed = ImageOps.fit(im.convert("RGB"), (512, 512),
                                   method=Image.Resampling.LANCZOS)
        upload = png(transformed)
        with self.assertRaisesRegex(FaceUploadBlocked, "transparency"):
            verify_sprite_face_upload(**opts(original, upload))

    def test_single_transparent_pixel_in_otherwise_valid_reference_blocks(self):
        # The installed transform does not composit alpha at all. Until
        # provenance approves an opaque source, partial alpha fails closed.
        im = Image.new("RGBA", (640, 800), (200, 100, 50, 255))
        for x in range(100, 350):
            for y in range(30, 160):
                im.putpixel((x, y), (20, 80, 140, 255))
        im.putpixel((1, 1), (90, 80, 70, 0))
        original = png(im)
        upload = png(ImageOps.fit(im.convert("RGB"), (512, 512),
                                  method=Image.Resampling.LANCZOS))
        with self.assertRaisesRegex(FaceUploadBlocked, "transparency"):
            verify_sprite_face_upload(**opts(original, upload))

    def test_symlink_or_file_path_not_accepted_as_image_bytes(self):
        source, upload, _ = fixture()
        args = opts(source, upload)
        args["canonical_bytes"] = Path("/tmp/some-face.png")
        with self.assertRaises(FaceUploadBlocked):
            verify_sprite_face_upload(**args)


if __name__ == "__main__":
    unittest.main()
