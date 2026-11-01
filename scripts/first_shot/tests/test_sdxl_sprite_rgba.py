"""CPU-only exact original -> RGBA derivative tests; no real Comfy/GPU submit."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("renderer_rgba_dispatch", HERE / "autonomous_dispatch.py")
dispatch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dispatch)
import sdxl_sprite_factor as sprite


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture(path, *, background=(246, 246, 246)):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (128, 192), background)
    ImageDraw.Draw(im).rectangle((41, 18, 87, 173), fill=(32, 54, 140))
    im.save(path, "PNG")
    return digest(path.read_bytes())


def crc_valid_but_undecodable(raw):
    out = bytearray(raw[:8])
    off = 8
    while off < len(raw):
        n = int.from_bytes(raw[off:off+4], "big")
        kind = raw[off+4:off+8]
        payload = raw[off+8:off+8+n]
        off += n+12
        if kind == b"IDAT":
            payload = zlib.compress(b"\x00")
        out.extend(len(payload).to_bytes(4, "big"))
        out.extend(kind)
        out.extend(payload)
        out.extend((zlib.crc32(kind + payload) & 0xffffffff).to_bytes(4, "big"))
    return bytes(out)


class RgbaOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.root = self.home / "lab" / "autonomous"
        self.id = "SPRITE_RGBA_R18"
        self.source = self.home / ".local/share/mcp-vn-comfy/output/original.png"
        self.source_sha = fixture(self.source)

    def _derive(self, sha=None):
        (self.root / "runs" / self.id).mkdir(parents=True, exist_ok=True)
        return sprite.derive_rgba_candidate(
            self.root, self.id, self.source, sha or self.source_sha)

    def test_exact_source_produces_distinct_sha_pinned_private_rgba_not_g2(self):
        evidence = self._derive()
        derived = self.root / "runs" / self.id / "sprite-rgba-candidate.png"
        self.assertEqual(evidence["original_png_sha256"], self.source_sha)
        self.assertEqual(digest(derived.read_bytes()), evidence["derived_rgba_sha256"])
        with Image.open(derived) as im:
            im.load()
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.getchannel("A").getextrema(), (0, 255))
        self.assertEqual(evidence["g2"], "NOT_REVIEWED")
        self.assertFalse(evidence["publish_eligible"])
        self.assertFalse(evidence["human_labeled"])
        self.assertFalse(evidence["published"])
        self.assertEqual(evidence["rgba_stage2"],
                         "INDEPENDENT_ORIGINAL_AND_DERIVED_PIXEL_REVIEW_REQUIRED")

    def test_modified_original_is_rejected_without_derivative(self):
        fixture(self.source, background=(240, 240, 240))
        with self.assertRaisesRegex(Exception, "SHA256 mismatch"):
            self._derive()
        self.assertFalse((self.root / "runs" / self.id / "sprite-rgba-candidate.png").exists())

    def test_existing_derived_output_is_never_overwritten(self):
        output = self.root / "runs" / self.id / "sprite-rgba-candidate.png"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"sentinel")
        with self.assertRaisesRegex(ValueError, "no_overwrite"):
            self._derive()
        self.assertEqual(output.read_bytes(), b"sentinel")

    def test_unsafe_background_fails_without_any_published_output(self):
        self.source_sha = fixture(self.source, background=(70, 10, 10))
        with self.assertRaises(Exception):
            self._derive()
        self.assertFalse((self.root / "runs" / self.id / "sprite-rgba-candidate.png").exists())

    def test_crc_valid_but_undecodable_original_fails_closed(self):
        raw = crc_valid_but_undecodable(self.source.read_bytes())
        self.source.write_bytes(raw)
        self.source_sha = digest(raw)
        with self.assertRaises(Exception):
            self._derive()
        self.assertFalse((self.root / "runs" / self.id / "sprite-rgba-candidate.png").exists())

    def test_invalid_experiment_id_does_not_create_path(self):
        (self.root / "runs").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "invalid_sprite_experiment_id"):
            sprite.derive_rgba_candidate(
                self.root, "../escape", self.source, self.source_sha)

    def test_runs_ancestor_symlink_rejected_before_private_rgba_write(self):
        outside = Path(self.tmp.name) / "other-sink"
        (outside / self.id).mkdir(parents=True)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "runs").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "missing_private_sprite_run"):
            sprite.derive_rgba_candidate(self.root, self.id, self.source, self.source_sha)
        self.assertFalse((outside / self.id / "sprite-rgba-candidate.png").exists())

    def test_comfy_original_ancestor_symlink_rejected_before_matte(self):
        outside = Path(self.tmp.name) / "other-original"
        outside.mkdir()
        source = outside / "original.png"
        source_sha = fixture(source)
        (self.home / "original-alias").symlink_to(outside, target_is_directory=True)
        (self.root / "runs" / self.id).mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "missing_or_unsafe_private_source"):
            sprite.derive_rgba_candidate(
                self.root, self.id, self.home / "original-alias" / "original.png", source_sha)
        self.assertFalse((self.root / "runs" / self.id / "sprite-rgba-candidate.png").exists())

    def test_rebound_path_at_matte_handoff_fails_closed(self):
        """An inode-pinned write must not report a different path's bytes."""
        from firstshot_source_matte import extract_matte
        run_dir = self.root / "runs" / self.id
        run_dir.mkdir(parents=True)
        displaced = Path(self.tmp.name) / "displaced-original-run"
        alternate = Path(self.tmp.name) / "alternate-run"
        alternate.mkdir()
        fake = alternate / "sprite-rgba-candidate.png"
        fake_sha = fixture(fake)

        def swap_after_open(pixels):
            result = extract_matte(pixels)
            run_dir.rename(displaced)
            run_dir.symlink_to(alternate, target_is_directory=True)
            return result

        with patch("firstshot_source_matte.extract_matte", side_effect=swap_after_open):
            with self.assertRaisesRegex(ValueError, "derived_rgba_path_rebound"):
                sprite.derive_rgba_candidate(self.root, self.id, self.source, self.source_sha)

        original_inode_output = displaced / "sprite-rgba-candidate.png"
        self.assertTrue(original_inode_output.is_file())
        self.assertNotEqual(digest(original_inode_output.read_bytes()), fake_sha)
        self.assertEqual(digest(fake.read_bytes()), fake_sha)

    def test_late_path_substitution_is_rejected_at_consumption(self):
        """Same PNG bytes at a substituted directory cannot impersonate origin inode."""
        evidence = self._derive()
        original = sprite.read_bound_rgba_bytes(self.root, self.id, evidence)
        self.assertEqual(digest(original), evidence["derived_rgba_sha256"])
        run_dir = self.root / "runs" / self.id
        moved = Path(self.tmp.name) / "displaced-original-run"
        run_dir.rename(moved)
        run_dir.mkdir()
        (run_dir / "sprite-rgba-candidate.png").write_bytes(original)
        with self.assertRaisesRegex(ValueError, "derived_rgba_path_rebound"):
            sprite.read_bound_rgba_bytes(self.root, self.id, evidence)

    def _simulate_tick(self, *, background=(246, 246, 246), undecodable=False):
        plan = {"id": self.id, "factor": "sdxl_sprite_body_source", "case": "SPRITE-CANONICAL"}
        pending = self.root / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        (pending / (self.id + ".json")).write_text(json.dumps(plan))
        prefix = "vn_sdxl_sprite_ab_" + self.id.lower() + "_"
        filename = prefix + "00001_.png"
        real_source = self.home / ".local/share/mcp-vn-comfy/output" / filename
        fixture(real_source, background=background)
        if undecodable:
            real_source.write_bytes(crc_valid_but_undecodable(real_source.read_bytes()))
        pid = "11111111-2222-3333-4444-555555555555"
        called = []
        def fake_api(route, payload=None, timeout=None):
            called.append(route)
            if route == "/prompt":
                return {"prompt_id": pid}
            if route == "/history/" + pid:
                return {pid: {
                    "status": {"status_str": "success"},
                    "outputs": {"7": {"images": [{
                        "filename": filename, "type": "output", "subfolder": ""
                    }]}}
                }}
            raise AssertionError("unexpected route " + route)
        with patch.object(dispatch, "validate", return_value=plan), \
             patch.object(dispatch, "build_graph_for_plan", return_value=({"7": {
                 "class_type": "SaveImage", "inputs": {"filename_prefix": prefix}
             }}, {"alpha_status": "NOT_PROVIDED_BY_NATIVE_VAE_GRAPH"})), \
             patch.object(dispatch.r, "queue_empty", return_value=True), \
             patch.object(dispatch.r, "api", side_effect=fake_api), \
             patch.object(dispatch.Path, "home", return_value=self.home):
            if undecodable:
                with self.assertRaises(Exception):
                    dispatch.tick(self.root)
                result = json.loads((self.root / "runs" / self.id / "result.json").read_text())
            else:
                result = dispatch.tick(self.root)
                # A review fence prevents a second simulated submit.
                again = dispatch.tick(self.root)
                self.assertEqual(again["status"], "WAIT_INDEPENDENT_ORIGINAL_PIXEL_REVIEW")
        return result, called

    def test_dispatcher_integrates_original_and_derived_shas_without_g2_or_publish(self):
        result, called = self._simulate_tick()
        self.assertEqual(result["status"], "GPU_FINISHED_REVIEW_REQUIRED")
        self.assertEqual(called.count("/prompt"), 1)
        record = json.loads((self.root / "runs" / self.id / "result.json").read_text())
        self.assertEqual(record["g1"], "PASS")
        self.assertEqual(record["g2"], "NOT_REVIEWED")
        self.assertEqual(record["alpha_status"], "DERIVED_RGBA_CANDIDATE_G2_UNVERIFIED")
        self.assertEqual(record["png_sha256"], record["original_png_sha256"])
        self.assertEqual(record["derived_rgba_sha256"], digest(
            (self.root / "runs" / self.id / "sprite-rgba-candidate.png").read_bytes()))
        self.assertIsNone(record["asset_enqueue_to_publish_eligible_seconds"])
        self.assertFalse(record["publish_eligible"])
        self.assertEqual(len(list((self.root / "review_pending").glob("*.json"))), 1)
        self.assertFalse(list((self.root / "running").glob("*.json")))

    def test_unsafe_matte_retains_original_and_review_fence(self):
        result, called = self._simulate_tick(background=(70, 10, 10))
        # Keep the status known to lab_exclusive.py so previously stopped
        # development services are restored after queue/history reconciliation.
        self.assertEqual(result["status"], "GPU_FINISHED_REVIEW_REQUIRED")
        self.assertEqual(result["postprocess_status"], "BLOCKED_UNSAFE")
        self.assertEqual(called.count("/prompt"), 1)
        record = json.loads((self.root / "runs" / self.id / "result.json").read_text())
        self.assertEqual(record["g1"], "PASS")
        self.assertEqual(record["g2"], "NOT_REVIEWED")
        self.assertEqual(record["alpha_status"], "POSTPROCESS_BLOCKED")
        self.assertEqual(record["postprocess_status"], "BLOCKED_UNSAFE")
        self.assertFalse(record["publish_eligible"])
        self.assertFalse((self.root / "runs" / self.id / "sprite-rgba-candidate.png").exists())
        self.assertEqual(len(list((self.root / "review_pending").glob("*.json"))), 1)

    def test_crc_valid_undecodable_comfy_output_is_not_technical_pass(self):
        result, called = self._simulate_tick(undecodable=True)
        self.assertEqual(called.count("/prompt"), 1)
        self.assertEqual(result["status"], "STOP_UNKNOWN_OR_FAILED_NO_RETRY")
        self.assertEqual(result["g1"], "NOT_MEASURED")
        self.assertFalse((self.root / "runs" / self.id / "sprite-rgba-candidate.png").exists())
        self.assertEqual(len(list((self.root / "running").glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
