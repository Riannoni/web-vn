import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"worker"))
from scene_caption_contract import scene_caption_conflicts, caption_asserts_single_person

class SceneCaptionContractTest(unittest.TestCase):
 def test_ambiguous_short_caption_is_not_accepted(self):
  issues=scene_caption_conflicts([{"name":"Mira","outfit":"green cloak"}],"Two.")
  self.assertIn("VLM did not describe CG contents well enough to verify the scene",issues)
 def test_exact_bad_cg_caption_is_rejected(self):
  caption=("One adult is standing with her back to us while another stands facing "
           "forward. The woman has long hair tied up in a bun. She's wearing a blue top")
  problems=scene_caption_conflicts([{"name":"Mira","outfit":"unclothed"}],caption)
  self.assertEqual(len(problems),2)
 def test_consistent_caption_is_not_rejected(self):
  self.assertEqual(scene_caption_conflicts(
      [{"name":"Mira","outfit":"green coat"}],
      "One adult woman wearing a green coat in a market street."),[])
 def test_two_person_scene_not_falsely_rejected(self):
  self.assertEqual(scene_caption_conflicts(
      [{"name":"Mira","outfit":"traveler clothes"},
       {"name":"Lia","outfit":"robe"}],
      "Two people face one another in a courtyard."),[])

class CaptionCountTest(unittest.TestCase):
 def test_two_people_described_without_exact_count(self):
  self.assertFalse(caption_asserts_single_person(
      "A man is sitting on a bench with a woman wearing a green cloak."))
  self.assertFalse(caption_asserts_single_person(
      "A person stands near another person in the market."))
 def test_only_one_asserted(self):
  self.assertTrue(caption_asserts_single_person("There is only one person in this scene."))
  self.assertTrue(caption_asserts_single_person("A single woman is standing in the forest."))
  self.assertTrue(caption_asserts_single_person("Exactly one adult figure is visible."))
 def test_negated_only_one_is_not_positive_solo_evidence(self):
  self.assertFalse(caption_asserts_single_person(
      "Not only one person appears; two people are clearly visible."))
 def test_solo_with_explicit_second_actor_is_not_solo_evidence(self):
  self.assertFalse(caption_asserts_single_person(
      "Only one woman stands in the foreground, but another man is behind her."))
 def test_negated_second_person_is_not_extra_person_evidence(self):
  caption=("One woman in a green coat stands alone in the marketplace. "
           "No second person is visible anywhere in the scene.")
  self.assertEqual(scene_caption_conflicts(
      [{"name":"Mira","outfit":"green coat"}],caption),[])
 def test_negated_two_people_is_not_extra_person_evidence(self):
  caption=("One woman wearing a green coat stands in the market square. "
           "There are not two people visible in the frame.")
  self.assertEqual(scene_caption_conflicts(
      [{"name":"Mira","outfit":"green coat"}],caption),[])
 def test_mixed_negation_and_actual_extra_still_rejected(self):
  caption=("No second person is near the foreground, but another woman "
           "stands clearly at the market gate behind the main woman.")
  self.assertIn("Neural CG contains an additional principal figure according to VLM",
      scene_caption_conflicts([{"name":"Mira","outfit":"green coat"}],caption))
 def test_negated_multiple_count_preserves_valid_solo(self):
  self.assertTrue(caption_asserts_single_person(
      "There is only one person visible, not two people."))
 def test_generic_indefinite_is_not_solo(self):
  self.assertFalse(caption_asserts_single_person("A woman wears a coat. A man stands next to her."))
if __name__=="__main__":
 unittest.main()
