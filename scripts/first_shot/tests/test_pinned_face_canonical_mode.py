"""Synthetic negative-first mode checks for the exact pinned Comfy face consumer.

These tests contain no canonical face, story, game source, or Comfy submission.
The upstream canonical face-upload boundary admits only decoded RGB PNGs;
the separate Comfy node must not silently discard alpha or palette semantics.
"""
from __future__ import annotations

import base64
import hashlib
import io
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfy_custom_nodes.web_vn_pinned_face import (
    decode_pinned_face_png,
    encode_pinned_face_png,
)


def _png_fixture(mode: str, *, transparent: bool = False):
    if mode == "P":
        image = Image.new("P", (512, 512), 1)
        image.putpalette([0, 0, 0, 40, 120, 220] + [0, 0, 0] * 254)
        if transparent:
            image.info["transparency"] = 0
    elif mode == "LA":
        image = Image.new("LA", (512, 512), (120, 0 if transparent else 255))
    elif mode == "RGBA":
        image = Image.new("RGBA", (512, 512),
                          (245, 5, 10, 0 if transparent else 255))
    elif mode == "RGB":
        image = Image.new("RGB", (512, 512), (11, 42, 223))
        image.putpixel((0, 0), (88, 75, 60))
    else:
        image = Image.new(mode, (512, 512), 127)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    raw = buffer.getvalue()
    return raw, hashlib.sha256(raw).hexdigest()


class CanonicalPinnedFaceModeTests(unittest.TestCase):
    def test_rgb_preserves_actual_pixels_and_sha_bound_bytes(self):
        raw, sha = _png_fixture("RGB")
        encoded = base64.b64encode(raw).decode("ascii")
        output = decode_pinned_face_png(encoded, sha)
        self.assertEqual((output.mode, output.size), ("RGB", (512, 512)))
        self.assertEqual(output.getpixel((0, 0)), (88, 75, 60))
        self.assertEqual(output.getpixel((1, 0)), (11, 42, 223))
        self.assertEqual(encode_pinned_face_png(raw, sha), encoded)

    def test_correctly_hashed_non_rgb_pngs_fail_closed(self):
        variants = [
            ("RGBA", False), ("RGBA", True),
            ("LA", False), ("LA", True),
            ("P", False), ("P", True),
            ("L", False),
        ]
        for mode, transparent in variants:
            with self.subTest(mode=mode, transparent=transparent):
                raw, sha = _png_fixture(mode, transparent=transparent)
                encoded = base64.b64encode(raw).decode("ascii")
                with self.assertRaisesRegex(ValueError, "pinned_face_invalid_mode"):
                    decode_pinned_face_png(encoded, sha)
                with self.assertRaisesRegex(ValueError, "pinned_face_invalid_mode"):
                    encode_pinned_face_png(raw, sha)


if __name__ == "__main__":
    unittest.main()
