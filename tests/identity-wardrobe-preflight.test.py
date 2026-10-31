"""Zero-GPU regression checks for immutable identity+wardrobe source preflight."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"worker"))
from identity_wardrobe_preflight import preflight,ContractBlocked

FACE_A="11111111-1111-1111-1111-111111111111.png"
FACE_B="22222222-2222-2222-2222-222222222222.png"
LEDGER={FACE_A:"a"*64,FACE_B:"b"*64}

def actor(name="Actor_A",face=FACE_A,outfit="closed navy jacket",region=None):
    return {"name":name,"anchor_face_asset":face,"anchor_asset":FACE_A,
            "outfit":outfit,"actor_region":region}
def scene(actors=None):
    actors=actors or [actor()]
    principals=[{"name":a["name"],"anchor_face_asset":a["anchor_face_asset"],
                 "outfit":a["outfit"],"region":a["actor_region"]} for a in actors]
    return {"kind":"scene","spec":{"kind":"scene","composition":"neural_story",
        "characters":actors,"visual_contract":{"version":1,
        "principals":principals,"crowd":{"policy":"none"},"contacts":[]}}}
def checked(job,**options):
    return preflight(job,backend=options.get("backend","sdxl"),
       conditioning=options.get("conditioning","sdxl_ipadapter_face"),
       face_sha256_by_asset=options.get("ledger",LEDGER),
       body_seed=options.get("body_seed"))

class IdentityWardrobePreflight(unittest.TestCase):
    def test_one_actor_creation_time_intent_only(self):
        result=checked(scene())
        self.assertEqual(result["status"],"SOURCE_INTENT_CONSISTENT_NOT_G2")
        self.assertEqual(result["actors"][0]["outfit"],"closed navy jacket")
        self.assertNotIn("G2_PASS",str(result))

    def test_real_reference_must_be_face_only_not_old_body(self):
        j=scene()
        j["spec"]["characters"][0]["anchor_face_asset"]=""
        j["spec"]["visual_contract"]["principals"][0]["anchor_face_asset"]=""
        with self.assertRaisesRegex(ContractBlocked,"Face-only"):
            checked(j)

    def test_forged_or_missing_immutable_face_checksum_is_rejected(self):
        with self.assertRaisesRegex(ContractBlocked,"checksum"):
            checked(scene(),ledger={FACE_A:"not-a-sha"})
        with self.assertRaisesRegex(ContractBlocked,"checksum"):
            checked(scene(),ledger={})

    def test_typed_outfit_differs_from_source_actor(self):
        j=scene()
        j["spec"]["visual_contract"]["principals"][0]["outfit"]="old green cloak"
        with self.assertRaisesRegex(ContractBlocked,"outfit"):
            checked(j)

    def test_swapped_canonical_face_reference(self):
        j=scene()
        j["spec"]["visual_contract"]["principals"][0]["anchor_face_asset"]=FACE_B
        with self.assertRaisesRegex(ContractBlocked,"swapped"):
            checked(j)

    def test_missing_or_ambiguous_wardrobe_refuses_source_consistency(self):
        for wrong in ("","default","unknown"):
            j=scene([actor(outfit=wrong)])
            with self.subTest(wrong=wrong),self.assertRaises(ContractBlocked):
                checked(j)

    def test_multi_actor_requires_grounded_regions_not_guessed_columns(self):
        two=[actor(),actor("Actor_B",FACE_B,"brown travel coat")]
        with self.assertRaisesRegex(ContractBlocked,"regions"):
            checked(scene(two))

    def test_multi_actor_cast_and_face_are_scoped(self):
        a=actor(region=[0.08,0.15,0.35,0.7])
        b=actor("Actor_B",FACE_B,"brown travel coat",[0.55,0.12,0.34,0.7])
        result=checked(scene([a,b]))
        self.assertEqual(result["actor_count"] if "actor_count" in result else
                         len(result["actors"]),2)
        self.assertEqual(result["actors"][1]["outfit"],"brown travel coat")

    def test_distinct_principals_cannot_inherit_one_face(self):
        a=actor(region=[0.05,0.1,0.35,0.75])
        b=actor("Actor_B",FACE_A,"brown travel coat",[0.55,0.1,0.35,0.75])
        with self.assertRaisesRegex(ContractBlocked,"reused"):
            checked(scene([a,b]))

    def test_native_zimage_union_pose_is_not_canonical_identity(self):
        with self.assertRaisesRegex(ContractBlocked,"unproven"):
            checked(scene(),backend="zimage")
        with self.assertRaisesRegex(ContractBlocked,"unproven"):
            checked(scene(),backend="zimage",conditioning="sdxl_ipadapter_face")

    def test_sdxl_without_face_conditioning_not_source_ready(self):
        with self.assertRaisesRegex(ContractBlocked,"IPAdapter|adapter"):
            checked(scene(),conditioning="text_only")

    def test_sprite_changed_outfit_uses_face_only_or_current_body(self):
        spec={"kind":"sprite","character":"Actor_A","face_asset":FACE_A,
              "variant":{"outfit":"closed navy jacket","pose":"standing"}}
        j={"kind":"sprite","character":"Actor_A","spec":spec}
        self.assertEqual(checked(j)["status"],"SOURCE_INTENT_CONSISTENT_NOT_G2")
        with self.assertRaisesRegex(ContractBlocked,"Stale"):
            checked(j,body_seed={"outfit":"old green cloak","sha256":"c"*64})
        self.assertEqual(checked(j,body_seed={
            "outfit":"closed navy jacket","sha256":"c"*64})["status"],
            "SOURCE_INTENT_CONSISTENT_NOT_G2")

    def test_lost_scene_contract_rejected(self):
        j=scene()
        del j["spec"]["visual_contract"]
        with self.assertRaisesRegex(ContractBlocked,"contract"):
            checked(j)

if __name__=="__main__":
    unittest.main()
