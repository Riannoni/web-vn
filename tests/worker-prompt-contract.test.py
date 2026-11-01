"""Regression coverage for storytelling-to-Comfy generation boundaries.

Stdlib-only: extract the prompt builder and its pure helper, not GPU runtime modules.
"""
import ast
import re
import unittest
import sys
from pathlib import Path

WORKER=Path(__file__).resolve().parents[1]/"worker"/"worker.py"
sys.path.insert(0,str(WORKER.parent))
from render_invariants import narrator_invariants
from render_retry import retry_plan
from pose_presets import pose_prompt
from engine_policy import assert_engine_snapshot
from wardrobe_contract import wants_unclothed
from scene_contract import crowd_condition


class WorkerPromptContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=WORKER.read_text()
        tree=ast.parse(source)
        names={"prompt_builder","compact_negative_prompt"}
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        module=ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[]))
        namespace={
            "re":re,
            "assert_engine_snapshot":assert_engine_snapshot,
            "retry_plan":retry_plan,
            "narrator_invariants":narrator_invariants,
            "pose_prompt":pose_prompt,
            "wants_unclothed":wants_unclothed,
            "background_context":lambda _:( "overcast", ""),
            "appearance_tags":lambda _: "adult with dark hair",
            "neural_scene_guards":lambda *_:("SOLO SUBJECT. ","duplicate person, ","v1"),
            "scene_constraints":lambda *_:("SCENE_CONTRACT. ","worn clothing"),
            "crowd_condition":crowd_condition
        }
        exec(compile(module,str(WORKER),"exec"),namespace)
        cls.prompt_builder=staticmethod(namespace["prompt_builder"])
        cls.source=source

    def test_forest_scene_is_never_forced_into_market_or_unclothed(self):
        j={"kind":"scene","style":"semireal","prompt":
           "One adult traveler standing in a forest clearing, front view.",
           "attempts":1,"spec":{"location":"Pine forest","composition":"neural_story",
           "narrator_prompt":True,"environment":{"id":"outdoor_forest",
           "positive":["pine woods"],"negative":["city buildings"]},
           "characters":[{"name":"Ada","appearance":"adult with dark hair"}]}}
        positive,negative=self.prompt_builder(j,None)
        self.assertIn("forest clearing",positive)
        self.assertNotIn("Market square with brick buildings",positive)
        self.assertNotIn("MUST BE FULLY NUDE",positive)
        self.assertNotIn("MUST BE FROM BEHIND",positive)
        self.assertNotIn("rating_explicit",positive)
        self.assertIn("duplicate person",negative)

    def test_keyword_wall_does_not_force_unrelated_camera_pose(self):
        j={"kind":"scene","style":"semireal","prompt":
           "One adult in front of a wall facing the viewer.",
           "attempts":1,"spec":{"location":"Hallway",
           "environment":{"id":"indoor_room","positive":["hallway"],"negative":[]},
           "characters":[{"name":"Ada","appearance":"adult"}]}}
        positive,_=self.prompt_builder(j,None)
        self.assertIn("facing the viewer",positive)
        self.assertNotIn("MUST BE FROM BEHIND",positive)
        self.assertNotIn("MUST BE FULLY NUDE",positive)
        self.assertNotIn("Market square with brick buildings",positive)

    def test_no_fallback_forces_failed_qa_to_pass(self):
        self.assertNotIn("QUALITY_ACCEPTED_FALLBACK",self.source)
        self.assertNotIn('report["passed"]=True',self.source)
        self.assertIn('print("QUALITY_REJECTED"',self.source)


if __name__=="__main__":
    unittest.main()
