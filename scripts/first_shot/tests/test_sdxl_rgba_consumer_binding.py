"""CPU-only downstream independent-review consumer binding regression."""
import hashlib
import io
import sys
import tempfile
from pathlib import Path
import unittest
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import independent_review as review


class DownstreamByteBindingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "lab"
        self.name = "SPRITE_BOUND_R01"
        self.run = self.root / "runs" / self.name
        self.run.mkdir(parents=True)
        source = Image.new("RGB", (32, 48), (140, 30, 40))
        orig = io.BytesIO()
        source.save(orig, "PNG")
        self.original = self.run / "original.png"
        self.original.write_bytes(orig.getvalue())
        alpha = Image.new("RGBA", (32, 48), (0, 0, 0, 0))
        ImageDraw.Draw(alpha).rectangle((8, 5, 24, 44), fill=(30, 50, 170, 255))
        buf = io.BytesIO()
        alpha.save(buf, "PNG")
        self.raw = buf.getvalue()
        self.derivative = self.run / "sprite-rgba-candidate.png"
        self.derivative.write_bytes(self.raw)
        r, f = self.run.stat(), self.derivative.stat()
        orig_sha = hashlib.sha256(orig.getvalue()).hexdigest()
        self.candidate = {
            "factor": "sdxl_sprite_body_source",
            "png_sha256": orig_sha,
            "original_png_sha256": orig_sha,
            "original_png_path": str(self.original),
            "derived_rgba_path": str(self.derivative),
            "derived_rgba_sha256": hashlib.sha256(self.raw).hexdigest(),
            "derived_rgba_run_dev": r.st_dev,
            "derived_rgba_run_ino": r.st_ino,
            "derived_rgba_file_dev": f.st_dev,
            "derived_rgba_file_ino": f.st_ino,
        }

    def test_ordinary_consumer_accepts_verified_rgba(self):
        self.assertIsNone(review._trusted_sprite_derivative(
            self.root, self.name, self.candidate))

    def test_consumer_rejects_changed_original_same_canvas(self):
        # Size-only reopens cannot prove the precise original PNG contents.
        changed = Image.new("RGB", (32, 48), (25, 80, 100))
        changed.save(self.original, "PNG")
        with self.assertRaisesRegex(ValueError, "private_source_sha_changed"):
            review._trusted_sprite_derivative(self.root, self.name, self.candidate)

    def test_consumer_rejects_replaced_run_inode_same_exact_png_bytes(self):
        old = self.root / "old-inode"
        self.run.rename(old)
        self.run.mkdir()
        (self.run / "sprite-rgba-candidate.png").write_bytes(self.raw)
        (self.run / "original.png").write_bytes((old / "original.png").read_bytes())
        with self.assertRaisesRegex(ValueError, "derived_rgba_path_rebound"):
            review._trusted_sprite_derivative(self.root, self.name, self.candidate)

    def test_consumer_rejects_symlinked_run_directory_same_exact_png_bytes(self):
        old = self.root / "old-inode"
        self.run.rename(old)
        shadow = self.root / "shadow"
        shadow.mkdir()
        (shadow / "sprite-rgba-candidate.png").write_bytes(self.raw)
        (shadow / "original.png").write_bytes((old / "original.png").read_bytes())
        self.run.symlink_to(shadow, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "derived_rgba_path_rebound"):
            review._trusted_sprite_derivative(self.root, self.name, self.candidate)


if __name__ == "__main__":
    unittest.main()
