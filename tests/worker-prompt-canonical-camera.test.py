"""Prompt/graph regression controls. Synthetic inputs; no network/model/GPU."""
import ast
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))
from PIL import Image, ImageDraw, ImageOps
from actor_layout import assert_cast_supported, region_for_actor
from engine_policy import assert_engine_snapshot
from neural_scene_guards import neural_scene_guards
from pose_presets import pose_control_guide, pose_prompt
from render_invariants import narrator_invariants
from render_retry import retry_plan
from scene_constraints import scene_constraints
from scene_contract import crowd_condition, scene_contract
from wardrobe_contract import wants_unclothed


def load_functions(source):
    tree = ast.parse(source)
    names = {"appearance_tags", "prompt_builder", "image_graph",
             "regional_face_attention_mask", "compact_negative_prompt"}
    module = ast.fix_missing_locations(ast.Module(body=[n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]))
    ns = dict(globals())
    ns.update(os=SimpleNamespace(environ={"VN_POSE_REFERENCE_ENABLED": "0",
                                         "VN_POSE_CONTROL": "0"}, urandom=lambda n: bytes(n)),
              STYLES={"semireal": ("CyberRealisticPony_V18.0_F16.safetensors", 32, 5.0)},
              background_context=lambda _: ("daylight", None),
              fetch_asset=lambda _: Image.new("RGBA", (96, 96), (80, 90, 100, 255)),
              upload_to_comfy=lambda _bytes, name: name,
              pil_png=lambda _: b"offline-synthetic-placeholder-not-a-png",
              resolve_scene_action=lambda *_: {"required": False},
              apply_inpaint_graph=lambda *_: False,
              print=lambda *_args, **_kwargs: None)
    exec(compile(module, "offline-worker-functions", "exec"), ns)
    return ns


def scene():
    return {"id": "offline-camera", "kind": "scene", "style": "semireal", "attempts": 1,
            "prompt": "Medium shot of Actor A smiling at Actor B in the established library.",
            "spec": {"composition": "neural_story", "narrator_prompt": True,
                     "background_asset": "synthetic-background.png", "location": "library",
                     "characters": [{"name": n, "anchor_face_asset": n + ".png",
                                     "outfit": "blue travel jacket"} for n in ("Actor A", "Actor B")]}}


class PromptCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (REPO / "worker" / "worker.py").read_text()
        cls.ns = load_functions(cls.source)

    def test_requested_camera_preserves_anchor_background_and_sampler(self):
        job = scene()
        new, _ = self.ns["image_graph"](job)
        self.assertIn("Medium shot", new["3"]["inputs"]["text"])
        self.assertNotIn("Wide environmental shot", new["3"]["inputs"]["text"])
        self.assertIn("requested camera framing", new["3"]["inputs"]["text"])
        self.assertEqual(new["5"]["inputs"]["latent_image"], ["11", 0])
        self.assertEqual(new["5"]["inputs"]["denoise"], 0.78)
        self.assertEqual(new["5"]["inputs"]["model"], ["67", 0])
        self.assertEqual(new["64"]["inputs"]["image"], ["62", 0])
        self.assertEqual(new["67"]["inputs"]["model"], ["64", 0])
        self.assertEqual(new["67"]["inputs"]["image"], ["65", 0])
        self.assertEqual(new["64"]["inputs"]["attn_mask"], ["63", 1])
        self.assertEqual(new["67"]["inputs"]["attn_mask"], ["66", 1])
        self.assertEqual(new["10"]["inputs"]["image"],
                         "mcp_vn_scene_environment_offline-camera.png")

    def test_default_canon_survives_but_explicit_outfit_does_not_copy_old_garments(self):
        job = {"kind": "sprite", "style": "semireal", "character": "Actor A", "attempts": 1,
               "prompt": "An adult traveler waves and smiles.", "spec": {
                   "narrator_prompt": True,
                   "appearance": "Взрослая женщина, короткие тёмные волосы, зелёный плащ.",
                   "variant": {"outfit": "default", "pose": "standing", "emotion": "happy"}}}
        text, _ = self.ns["prompt_builder"](job, None)
        self.assertIn(job["spec"]["appearance"], text)
        self.assertIn("short dark brown hair", text)
        self.assertIn("forest-green cloak", text)
        self.assertIn("Full-length body", text)
        job["spec"]["variant"]["outfit"] = "closed navy jacket"
        text, _ = self.ns["prompt_builder"](job, None)
        self.assertIn("closed navy jacket", text)
        self.assertIn("short dark brown hair", text)
        self.assertNotIn("forest-green cloak", text)
        self.assertNotIn("зелёный плащ", text)

    def test_negative_whole_clauses_tail_and_explicit_overflow(self):
        job = scene()
        job["spec"]["environment"] = {"negative": [
            "unrequested prop number " + str(i) for i in range(35)] + ["bad teeth", "BAD TEETH"]}
        _, compact = self.ns["prompt_builder"](job, None)
        clauses = lambda text: {x.strip().casefold() for x in text.split(",") if x.strip()}
        self.assertGreater(len(compact), 1000)
        for expected in job["spec"]["environment"]["negative"]:
            self.assertIn(expected.casefold(), clauses(compact))
        self.assertIn("score_4", compact)
        self.assertIn("extra teeth", compact)
        self.assertEqual(sum(x.strip().casefold() == "bad teeth" for x in compact.split(",")), 1)
        with self.assertRaisesRegex(ValueError, "Negative prompt exceeds"):
            self.ns["compact_negative_prompt"]("x" * 3001)
        job["prompt"] = "x" * 5501
        with self.assertRaisesRegex(ValueError, "Positive prompt exceeds"):
            self.ns["prompt_builder"](job, None)


    def test_weighted_bracketed_and_escaped_prompts_are_preserved_verbatim(self):
        values = (
            "(bad anatomy, bad hands:1.2), (bad anatomy, extra fingers:1.3)",
            "[bad anatomy, bad hands], [bad anatomy, extra fingers]",
            r"bad\,hands, bad\,hands",
        )
        for text in values:
            with self.subTest(text=text):
                self.assertEqual(self.ns["compact_negative_prompt"](text, len(text)), text)
                with self.assertRaisesRegex(ValueError, "Negative prompt exceeds"):
                    self.ns["compact_negative_prompt"](text, len(text) - 1)


if __name__ == "__main__":
    unittest.main()
