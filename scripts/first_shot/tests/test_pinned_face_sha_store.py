"""Synthetic CPU-only SHA face-store, graph/history privacy and negative tests."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfy_custom_nodes.web_vn_pinned_face.sha_store import read_pinned_store, stage_pinned_store
from comfy_custom_nodes.web_vn_pinned_face import (
    WebVNPinnedFacePNG, decode_pinned_face_from_store,
)


def _synthetic_face():
    image = Image.new("RGB", (512, 512), (203, 44, 66))
    image.putpixel((0, 0), (21, 130, 250))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class PrivateFaceStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "face_store"
        self.store.mkdir(mode=0o700)
        self.raw = _synthetic_face()
        self.sha = hashlib.sha256(self.raw).hexdigest()

    def test_sha_only_graph_history_log_fixture_has_no_face_bytes(self):
        self.assertEqual(stage_pinned_store(self.raw, self.sha, root=self.store), self.sha)
        node = {"class_type": "WebVNPinnedFacePNG",
                "inputs": {"sha256": self.sha}}
        fake_history = {"prompt": ["synthetic", 7, {"17": node}], "outputs": {}}
        fake_logs = ["node WebVNPinnedFacePNG " + self.sha]
        payload = json.dumps({"graph": {"17": node}, "history": fake_history,
                              "logs": fake_logs})
        self.assertNotIn("png_base64", payload)
        self.assertNotIn(base64.b64encode(self.raw).decode("ascii"), payload)
        self.assertNotIn("data:image/png", payload)
        self.assertEqual(set(WebVNPinnedFacePNG.INPUT_TYPES()["required"]), {"sha256"})
        self.assertEqual(read_pinned_store(self.sha, root=self.store), self.raw)
        self.assertEqual(stage_pinned_store(self.raw, self.sha, root=self.store), self.sha)
        self.assertEqual(len(list(self.store.glob("*.png"))), 1)
        self.assertEqual((self.store / (self.sha + ".png")).stat().st_mode & 0o777, 0o400)

    def test_missing_bad_sha_rehashed_mutation_and_mismatched_stage_block(self):
        stage_pinned_store(self.raw, self.sha, root=self.store)
        with self.assertRaisesRegex(ValueError, "invalid_sha"):
            read_pinned_store("../../other", root=self.store)
        with self.assertRaisesRegex(ValueError, "missing_or_unsafe_store_file"):
            read_pinned_store(hashlib.sha256(b"absent").hexdigest(), root=self.store)
        with self.assertRaisesRegex(ValueError, "sha_mismatch"):
            stage_pinned_store(b"different", self.sha, root=self.store)
        file = self.store / (self.sha + ".png")
        file.chmod(0o600)
        file.write_bytes(b"changed")
        file.chmod(0o400)
        with self.assertRaisesRegex(ValueError, "sha_mismatch"):
            read_pinned_store(self.sha, root=self.store)
        with self.assertRaisesRegex(ValueError, "sha_mismatch"):
            stage_pinned_store(self.raw, self.sha, root=self.store)

    def test_no_implicit_root_unsafe_permissions_and_symlink_block(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "store_unconfigured"):
                read_pinned_store(self.sha)
        with self.assertRaisesRegex(ValueError, "unsafe_path"):
            read_pinned_store(self.sha, root="relative")
        self.store.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "store_not_private"):
            read_pinned_store(self.sha, root=self.store)
        self.store.chmod(0o700)
        outside = self.root / "outside.png"
        outside.write_bytes(self.raw)
        (self.store / (self.sha + ".png")).symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "missing_or_unsafe_store_file"):
            read_pinned_store(self.sha, root=self.store)
        alias = self.root / "alias"
        alias.symlink_to(self.store, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "store_unavailable"):
            read_pinned_store(self.sha, root=alias)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "real torch not installed in lightweight hosted CI")
    def test_real_comfy_cpu_node_reads_only_sha_with_exact_pixels(self):
        stage_pinned_store(self.raw, self.sha, root=self.store)
        with patch.dict(os.environ, {"WEB_VN_PINNED_FACE_DIR": str(self.store)}):
            tensor, = WebVNPinnedFacePNG().load(self.sha)
            self.assertEqual(tuple(tensor.shape), (1, 512, 512, 3))
            self.assertAlmostEqual(float(tensor[0, 0, 0, 0]), 21 / 255, places=6)
            self.assertAlmostEqual(float(tensor[0, 0, 0, 1]), 130 / 255, places=6)
            self.assertEqual(
                decode_pinned_face_from_store(self.sha).getpixel((0, 0)),
                (21, 130, 250),
            )


if __name__ == "__main__":
    unittest.main()
