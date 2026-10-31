"""CPU-only identity/wardrobe regression tests; no private assets or GPU."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / "worker"))
from scene_constraints import scene_constraints

class IdentityWardrobeIntent(unittest.TestCase):
    def test_two_distinct_worn_outfits_are_actor_scoped(self):
        spec={"composition":"neural_story","characters":[
            {"name":"Actor_A","outfit":"closed navy jacket","pose":"standing"},
            {"name":"Actor_B","outfit":"brown travel coat","pose":"standing"}]}
        positive,negative=scene_constraints(spec,"Two adults in a market.")
        self.assertIn("Actor_A",positive)
        self.assertIn("closed navy jacket",positive)
        self.assertIn("Actor_B",positive)
        self.assertIn("brown travel coat",positive)
        self.assertNotIn("worn clothing",negative)

    def test_mixed_worn_and_unclothed_has_no_global_exclusion(self):
        spec={"composition":"neural_story","characters":[
            {"name":"Actor_A","outfit":"unclothed","pose":"standing"},
            {"name":"Actor_B","outfit":"buttoned blue jacket","pose":"standing"}]}
        positive,negative=scene_constraints(spec,"Two adults face the viewer.")
        self.assertIn("Actor_A",positive)
        self.assertIn("Actor_B",positive)
        self.assertIn("buttoned blue jacket",positive)
        self.assertNotIn("worn clothing",negative)

    def test_one_character_keeps_existing_current_wardrobe_rule(self):
        spec={"composition":"neural_story","characters":[
            {"name":"Actor_A","outfit":"closed navy jacket","pose":"standing"}]}
        positive,_=scene_constraints(spec,"One adult waits.")
        self.assertIn("CURRENT WARDROBE CONTRACT",positive)
        self.assertIn("closed navy jacket",positive)

if __name__=="__main__":
    unittest.main()
