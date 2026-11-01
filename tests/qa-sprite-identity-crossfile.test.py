"""Isolated cross-file worker/vision semantics: synthetic PNG and mocked daemon, no model/GPU."""
import io, os, sys, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

source = Path(os.environ.get("QA_SOURCE_TREE", Path(__file__).resolve().parents[1]))
os.environ.setdefault("VN_WORKER_TOKEN", "integration-synthetic")
sys.path.insert(0, str(source/"worker"))
import worker

class IntendedFaceApplicability(unittest.TestCase):
    def assess(self, pose, similarity, verdict, reason, caption, face=True):
        im = Image.new("RGBA", (128, 192), (0,0,0,0))
        ImageDraw.Draw(im).rectangle((32,8,95,187),fill=(130,95,70,255))
        b=io.BytesIO(); im.save(b,"PNG")
        spec={"resolution":[128,192],"quality":"standard",
              "variant":{"pose":pose,"outfit":"unspecified"}}
        if face: spec["face_asset"]="synthetic-reference"
        job={"id":"isolated-identity-contract", "kind":"sprite", "attempts":1,
             "spec":spec, "prompt":""}
        validation={"status":"passed","reasons":[],"identity_similarity":similarity,
                    "identity_face_visibility":verdict,"identity_decision_reason":reason,
                    "caption":caption,"duration_seconds":0}
        with patch.dict(os.environ,{"VN_VISION_QA":"1"}), \
             patch.object(worker,"cutout",side_effect=lambda x:x), \
             patch.object(worker,"harmonize",side_effect=lambda x,b:x), \
             patch.object(worker,"fetch_asset",return_value=im), \
             patch.object(worker,"request",return_value=validation):
            _, result=worker.assess(job,b.getvalue(),None)
        return result

    def test_front_borderline_cannot_publish(self):
        r=self.assess("standing",0.8175,"unobservable","face_similarity_borderline","person facing camera")
        self.assertFalse(r["passed"],r)
        self.assertEqual(r["evidence"]["identity"]["verdict"],"unobservable")
        self.assertAlmostEqual(r["evidence"]["identity"]["confidence"],0.8175)

    def test_corrob_rear_keeps_not_verified_but_can_pass_face_gate(self):
        r=self.assess("from behind",0.91,"unobservable","rear_pose_corrobated","person shown from behind")
        self.assertTrue(r["passed"],r)
        self.assertEqual(r["evidence"]["identity"]["verdict"],"unobservable")
        self.assertEqual(r["evidence"]["identity"]["reason"],"rear_pose_corrobated")

    def test_requested_rear_but_actual_front_must_fail_pose_contract(self):
        r=self.assess("from behind",0.91,"verified","face_similarity_sufficient","front-facing person with visible face")
        self.assertFalse(r["passed"],r)

    def test_visible_front_verified_stays_accepted(self):
        r=self.assess("standing",0.91,"verified","face_similarity_sufficient","front-facing person")
        self.assertTrue(r["passed"],r)

if __name__=="__main__": unittest.main(verbosity=2)
