"""CPU-only exact-source SDXL body-latent factor tests; never submit Comfy."""
import copy
import hashlib
import importlib.util
import json
import io
import zlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT_SRC = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("renderer_sdxl_dispatch", ROOT_SRC / "autonomous_dispatch.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
import sdxl_sprite_factor as sprite


def n(cls, **inp):
    return {"class_type": cls, "inputs": inp}


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, sort_keys=True, indent=2).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def crc_valid_but_undecodable_png(raw):
    """Replace IDAT with a valid CRC and a valid but undersized zlib stream."""
    assert raw[:8] == bytes.fromhex("89504e470d0a1a0a")
    output = bytearray(raw[:8])
    off = 8
    replaced = 0
    while off < len(raw):
        n = int.from_bytes(raw[off:off+4], "big")
        kind = raw[off+4:off+8]
        payload = raw[off+8:off+8+n]
        off += n+12
        if kind == b"IDAT":
            payload = zlib.compress(b"\x00")
            replaced += 1
        output += len(payload).to_bytes(4, "big") + kind + payload
        output += (zlib.crc32(kind + payload) & 0xffffffff).to_bytes(4, "big")
    assert off == len(raw) and replaced == 1
    corrupted = bytes(output)
    with Image.open(io.BytesIO(corrupted)) as im:
        im.verify()  # The failure must be in full pixel decoding, not CRC.
    return corrupted


class SDXLCanonicalSpriteFactorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.root = Path(self.tmp.name) / "private_lab"
        self.input = self.home / ".local/share/mcp-vn-comfy/input"
        self.input.mkdir(parents=True)
        self.asset = "00000000-0000-0000-0000-000000000001.png"
        img = self.root / "scratch.png"
        img.parent.mkdir(parents=True)
        # Opaque nonuniform face: an entirely flat image is correctly rejected
        # by the independently reviewed canonical-blank guard in PR #119.
        face_fixture = Image.new("RGB", (512, 512), (60, 70, 80))
        face_fixture.putpixel((0, 0), (240, 20, 20))
        face_fixture.save(img)
        face_bytes = img.read_bytes()
        self.face_sha = hashlib.sha256(face_bytes).hexdigest()
        face_source = self.root / "private_assets" / (self.face_sha + ".png")
        face_source.parent.mkdir(parents=True)
        face_source.write_bytes(face_bytes)
        (self.input / "face0.png").write_bytes(face_bytes)
        Image.new("RGB", (832, 1216), (120, 65, 40)).save(self.input / "body0.png")
        self.body_sha = hashlib.sha256((self.input / "body0.png").read_bytes()).hexdigest()
        self.job = {
            "kind": "sprite", "style": "semireal", "spec": {
                "character": "Actor_A", "face_asset": self.asset,
                "variant": {"outfit": "closed blue jacket"},
            }
        }
        self.graph = {
            "1": n("CheckpointLoaderSimple", ckpt_name=sprite.CHECKPOINT),
            "2": n("EmptyLatentImage", width=832, height=1216, batch_size=1),
            "3": n("CLIPTextEncode", clip=["8",0], text="synthetic subject, blue jacket"),
            "4": n("CLIPTextEncode", clip=["8",0], text="synthetic negative"),
            "5": n("KSampler", model=["18",0], positive=["3",0],
                   negative=["4",0], latent_image=["11",0], seed=12345,
                   steps=32, cfg=5.0, denoise=.64, sampler_name="dpmpp_2m",
                   scheduler="karras"),
            "6": n("VAEDecode", samples=["5",0], vae=["1",2]),
            "7": n("SaveImage", images=["6",0], filename_prefix="private-old"),
            "8": n("CLIPSetLastLayer", clip=["1",1], stop_at_clip_layer=-2),
            "10": n("LoadImage", image="body0.png"),
            "11": n("VAEEncode", pixels=["10",0], vae=["1",2]),
            "15": n("CLIPVisionLoader",
                    clip_name="CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"),
            "16": n("IPAdapterModelLoader",
                    ipadapter_file="ip-adapter-plus-face_sdxl_vit-h.safetensors"),
            "17": n("LoadImage", image="face0.png"),
            "18": n("IPAdapterAdvanced", model=["1",0], ipadapter=["16",0],
                    image=["17",0], clip_vision=["15",0], weight=.78,
                    start_at=0.0, end_at=.9, weight_type="linear",
                    combine_embeds="concat", embeds_scaling="V only"),
        }
        self.manifest = {
            "schema": "canonical_sdxl_sprite_baseline_v1",
            "job": self.job, "baseline_graph": self.graph,
            "source_job_sha256": sprite.digest(self.job),
            "baseline_graph_sha256": sprite.digest(self.graph),
            "save_version": 10, "scene_contract_sha256": "a"*64,
            "face_original_sha256": self.face_sha,
            "outfit_revision_sha256": sprite.digest("closed blue jacket"),
            "checkpoint_sha256": "b"*64,
            "adapter_sha256": "c"*64,
            "clipvision_sha256": "d"*64,
            "face_uploads": {"Actor_A": {
                "image": "face0.png", "source_sha256": self.face_sha,
                "upload_sha256": self.face_sha,
            }},
            "body_seed": {"image": "body0.png", "upload_sha256": self.body_sha,
                          "outfit": "old red coat"},
            "seed": 12345,
            "prompt_pair_sha256": sprite.digest(["synthetic subject, blue jacket",
                                                  "synthetic negative"]),
        }
        self.receipt = {
            "schema": "creation_bound_sprite_v1",
            "source_job_sha256": self.manifest["source_job_sha256"],
            "scene_contract_sha256": self.manifest["scene_contract_sha256"],
            "outfit_revision_sha256": self.manifest["outfit_revision_sha256"],
            "face_original_sha256": self.face_sha,
            "save_version": 10,
            "frozen_actor_id": "Actor_A",
            "frozen_face_asset": self.asset,
            "frozen_current_outfit": "closed blue jacket",
        }
        self.repin()

    def repin(self):
        self.manifest["source_job_sha256"] = sprite.digest(self.manifest["job"])
        self.manifest["baseline_graph_sha256"] = sprite.digest(self.manifest["baseline_graph"])
        receipt_sha = save_json(self.root / "creation_receipts" / "scratch.json", self.receipt)
        self.manifest["creation_receipt_sha256"] = receipt_sha
        (self.root / "creation_receipts" / "scratch.json").replace(
            self.root / "creation_receipts" / (receipt_sha + ".json"))
        source_sha = save_json(self.root / "private_sources" / "scratch.json", self.manifest)
        (self.root / "private_sources" / "scratch.json").replace(
            self.root / "private_sources" / (source_sha + ".json"))
        self.plan = {
            "schema": "firstshot_one_factor_v1",
            "id": "SPRITE_SDXL_BODY_R16",
            "case": sprite.CASE,
            "base_case_sha256": source_sha,
            "factor": sprite.FACTOR,
            "new_value": sprite.VALUE,
            "hypothesis": "A source-bound SDXL face adapter plus fresh latent may prevent historical full-body garment leakage in the current outfit.",
            "falsifier": "The original output violates current outfit, canonical visible face, RGBA transparency or full-body framing.",
            "author_task": "R-16",
        }
        return self.plan

    def _validate(self, plan=None):
        with patch.object(m.Path, "home", return_value=self.home):
            return m.validate(plan or self.plan, root=self.root)

    def _build(self, plan=None):
        with patch.object(m.Path, "home", return_value=self.home):
            return m.build_graph_for_plan(plan or self.plan, None,
                                          "private_sdxl_ab_123_", root=self.root)

    def test_one_factor_uses_exact_pinned_private_sdxl_source(self):
        self.assertIs(self._validate(), self.plan)
        graph, evidence = self._build()
        b = copy.deepcopy(self.manifest["baseline_graph"])
        self.assertEqual(graph["5"]["inputs"]["latent_image"], ["2",0])
        self.assertEqual(graph["5"]["inputs"]["denoise"], 1.0)
        self.assertEqual(graph["7"]["inputs"]["filename_prefix"], "private_sdxl_ab_123_")
        graph["5"]["inputs"]["latent_image"] = ["11",0]
        graph["5"]["inputs"]["denoise"] = .64
        graph["7"]["inputs"]["filename_prefix"] = "private-old"
        self.assertEqual(graph, b)
        self.assertEqual(evidence["source_job_sha256"], sprite.digest(self.job))
        self.assertEqual(evidence["g2"], "NOT_REVIEWED")
        self.assertEqual(evidence["producer_trust"], "SHA_BOUND_REQUIRES_INDEPENDENT_ORIGIN_REVIEW")
        self.assertEqual(evidence["alpha_status"], "NOT_PROVIDED_BY_NATIVE_VAE_GRAPH")
        self.assertFalse(evidence["publish_eligible"])
        self.assertNotIn("checkpoint_sha256_attested", evidence)

    def test_rejects_crc_valid_undecodable_face_before_gpu(self):
        data = crc_valid_but_undecodable_png((self.input / "face0.png").read_bytes())
        self.face_sha = hashlib.sha256(data).hexdigest()
        (self.root / "private_assets" / (self.face_sha + ".png")).write_bytes(data)
        (self.input / "face0.png").write_bytes(data)
        self.manifest["face_original_sha256"] = self.face_sha
        self.manifest["face_uploads"]["Actor_A"]["source_sha256"] = self.face_sha
        self.manifest["face_uploads"]["Actor_A"]["upload_sha256"] = self.face_sha
        self.receipt["face_original_sha256"] = self.face_sha
        self.repin()
        with self.assertRaisesRegex(ValueError, "invalid_png_pixels"):
            self._validate()

    def test_rejects_crc_valid_undecodable_body_upload_before_gpu(self):
        data = crc_valid_but_undecodable_png((self.input / "body0.png").read_bytes())
        (self.input / "body0.png").write_bytes(data)
        self.manifest["body_seed"]["upload_sha256"] = hashlib.sha256(data).hexdigest()
        self.repin()
        with self.assertRaisesRegex(ValueError, "invalid_png_pixels"):
            self._validate()

    def test_missing_private_face_original_never_queues(self):
        (self.root / "private_assets" / (self.face_sha + ".png")).unlink()
        with patch.object(m.Path, "home", return_value=self.home),              patch.object(m.r, "api", side_effect=AssertionError("no Comfy calls")):
            with self.assertRaises(ValueError):
                m.queue(self.root, self.plan)
        self.assertEqual(list((self.root / "pending").glob("*.json")), [])

    def test_missing_face_upload_never_queues(self):
        (self.input / "face0.png").unlink()
        with self.assertRaises(ValueError):
            self._validate()

    def test_changed_uploaded_face_bytes_rejected(self):
        Image.new("RGB", (512,512), (1,2,3)).save(self.input / "face0.png")
        with self.assertRaisesRegex(ValueError, "private_source_sha_changed"):
            self._validate()

    def test_rejects_rehashed_substituted_face_pixels(self):
        Image.new("RGB", (512, 512), (17, 5, 199)).save(self.input / "face0.png")
        actual = (self.input / "face0.png").read_bytes()
        # Attacker legitimately recomputed the transport checksum, but not
        # the immutable canonical original pixels.
        self.manifest["face_uploads"]["Actor_A"]["upload_sha256"] = hashlib.sha256(actual).hexdigest()
        self.repin()
        with self.assertRaisesRegex(ValueError, "canonical_face_upload_pixels_do_not_match"):
            self._validate()

    def test_rejects_creation_receipt_wrong_frozen_actor(self):
        self.receipt["frozen_actor_id"] = "Actor_B"
        self.repin()
        with self.assertRaisesRegex(ValueError, "canonical_actor_attribution_mismatch"):
            self._validate()

    def test_rejects_creation_receipt_wrong_frozen_outfit(self):
        self.receipt["frozen_current_outfit"] = "old red coat"
        self.repin()
        with self.assertRaisesRegex(ValueError, "canonical_current_outfit_mismatch"):
            self._validate()

    def test_positive_evidence_declares_only_cpu_pixel_binding(self):
        _, evidence = self._build()
        self.assertTrue(evidence["canonical_face_upload_pixels_match_cpu"])
        self.assertFalse(evidence["origin_authenticated"])
        self.assertFalse(evidence["publish_eligible"])

    def test_creation_receipt_missing_blocks(self):
        (self.root / "creation_receipts" / (self.manifest["creation_receipt_sha256"]+".json")).unlink()
        with self.assertRaises(ValueError):
            self._validate()

    def test_source_job_or_outfit_changed_after_freeze_blocks(self):
        self.manifest["job"]["spec"]["variant"]["outfit"] = "old red coat"
        self.repin()
        with self.assertRaisesRegex(ValueError, "current_outfit_sha_mismatch"):
            self._validate()

    def test_disconnected_face_adapter_fallback_blocks(self):
        self.graph["5"]["inputs"]["model"] = ["1",0]
        self.repin()
        with self.assertRaisesRegex(ValueError, "Sampler bypasses"):
            self._validate()

    def test_missing_ipadapter_node_blocks(self):
        self.graph.pop("18")
        self.repin()
        with self.assertRaisesRegex(ValueError, "IPAdapter"):
            self._validate()

    def test_cross_family_zimage_checkpoint_blocks(self):
        self.graph["1"]["inputs"]["ckpt_name"] = "z_image_turbo.safetensors"
        self.repin()
        with self.assertRaisesRegex(ValueError, "model_family"):
            self._validate()

    def test_body_seed_must_be_historical_different_outfit(self):
        self.manifest["body_seed"]["outfit"] = "closed blue jacket"
        self.repin()
        with self.assertRaisesRegex(ValueError, "historical_body_outfit_not_distinct"):
            self._validate()

    def test_missing_body_upload_blocks(self):
        (self.input / "body0.png").unlink()
        with self.assertRaises(ValueError):
            self._validate()

    def test_changed_seed_rejected_even_with_rehashed_graph(self):
        self.graph["5"]["inputs"]["seed"] += 1
        self.repin()
        with self.assertRaisesRegex(ValueError, "baseline_seed_changed"):
            self._validate()

    def test_refuses_unapproved_factor_or_hidden_extra_field(self):
        with self.assertRaises(ValueError):
            self._validate({**self.plan,"factor":"checkpoint"})
        with self.assertRaises(ValueError):
            self._validate({**self.plan,"new_value":"switch_model"})
        with self.assertRaises(ValueError):
            self._validate({**self.plan,"checkpoint":"another.safetensors"})

    def test_rejects_missing_or_wrong_source_baseline_digest(self):
        with self.assertRaises(ValueError):
            self._validate({**self.plan, "base_case_sha256": "a"*64})

    def test_existing_review_blocks_new_queue(self):
        (self.root / "review_pending").mkdir(parents=True)
        (self.root / "review_pending" / "PRIOR_CASE.json").write_text("{}")
        with patch.object(m.Path,"home",return_value=self.home):
            answer = m.queue(self.root, self.plan)
        self.assertEqual(answer["reason"], "one_candidate_requires_review")

    def test_guard_existing_legacy_prompt_and_pose_cases(self):
        old = {"schema":"firstshot_one_factor_v1","id":"SPRITE_SDXL_BODY_R16",
               "case":"SPR-01","base_case_sha256":m.base_sha("SPR-01"),
               "factor":"prompt_text","new_value":"synthetic different prompt",
               "hypothesis":self.plan["hypothesis"],"falsifier":self.plan["falsifier"],
               "author_task":"R-16"}
        self.assertIs(m.validate(old),old)
        with self.assertRaisesRegex(ValueError, "unapproved_sdxl_sprite_factor"):
            self._validate({**self.plan,"case":"SPR-01"})


    def test_rejects_save_image_bypassing_sampler(self):
        self.graph["7"]["inputs"]["images"] = ["10", 0]
        self.repin()
        with self.assertRaisesRegex(ValueError, "sprite_output_not_from_sampler"):
            self._validate()

    def test_rejects_decode_bypassing_sampler(self):
        self.graph["6"]["inputs"]["samples"] = ["11", 0]
        self.repin()
        with self.assertRaisesRegex(ValueError, "sprite_output_not_from_sampler"):
            self._validate()

    def test_rejects_decode_using_unrelated_vae(self):
        self.graph["6"]["inputs"]["vae"] = ["12", 0]
        self.repin()
        with self.assertRaisesRegex(ValueError, "sprite_output_not_from_sampler"):
            self._validate()

    def test_rejects_hidden_second_save_image(self):
        self.graph["99"] = n("SaveImage", images=["10", 0], filename_prefix="other")
        self.repin()
        with self.assertRaisesRegex(ValueError, "unexpected_extra_output_sink"):
            self._validate()


if __name__ == "__main__":
    unittest.main()
