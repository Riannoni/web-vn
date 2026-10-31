"""Read-only, fail-closed preflight for ONE experimental rear-oblique pose A/B.

This module never authorizes a GPU submission, signs a production guide, or
changes the existing approved-reference manifest. Its output is an evidence
proposal for an independently brokered, disposable, single-factor lab test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
from pathlib import Path

from PIL import Image


class LabPoseError(ValueError):
    pass


# The one grounded source/guide and the public frozen pack for CG-03 v1.
# Do not accept an updated source+manifest, or an edited pack, as the same A/B.
# A new baseline needs a separately reviewed hash set and a new proposal version.
PINNED_CG03_01 = {
    "reference": "730b51efb109b5c6834ada6699d43141f17111f8731f05ea5416bcd9d71bc631",
    "guide": "7391e30022bc83c89a4d5105c1efd5ce939d9cd460648a0ff7aa6121109793a2",
    "extraction": "d506a43e308cc8f9a30885f74223a35689d5b95101d289ad4b898edb10e1018b",
    "pack": "aa5a8f94859ff6b5e8c99386757cc9fccd1fa5e88a2fdd3e6970e556f8438910",
}

REQUIRED_PHOTO_OBSERVATIONS = (
    "rear_three_quarter",
    "vertical_wall",
    "both_palms_visible_on_wall",
    "forward_lean",
    "both_feet_visible",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise LabPoseError("invalid_relative_path")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise LabPoseError("missing_or_escaping_file")
    return resolved


def _joints(raw):
    frame = raw[0] if isinstance(raw, list) and len(raw) == 1 else raw
    people = frame.get("people") if isinstance(frame, dict) else None
    if not isinstance(people, list) or len(people) != 1:
        raise LabPoseError("expected_one_source_person")
    coords = people[0].get("pose_keypoints_2d", [])
    if len(coords) != 54:
        raise LabPoseError("invalid_coco18")
    result = []
    for index in range(18):
        try:
            x, y, confidence = map(float, coords[index * 3:index * 3 + 3])
        except (ValueError, TypeError) as exc:
            raise LabPoseError("invalid_joint_value") from exc
        if not all(map(math.isfinite, (x, y, confidence))):
            raise LabPoseError("nonfinite_joint")
        result.append((x, y, confidence))
    return result


def _geometry(joints, width, height):
    # COCO18: 1 neck, 2/5 shoulders, 4/7 wrists, 8/11 hips,
    # 10/13 ankles. Full joint coverage is a LAB prerequisite, not contact QA.
    if any(conf < .25 for _, _, conf in joints):
        raise LabPoseError("missing_required_joint")
    if any(not (0 <= x < width and 0 <= y < height) for x, y, _ in joints):
        raise LabPoseError("joint_outside_photo")
    neck = joints[1]
    hips = ((joints[8][0] + joints[11][0]) / 2,
            (joints[8][1] + joints[11][1]) / 2)
    dx, dy = hips[0] - neck[0], hips[1] - neck[1]
    if dy <= 0:
        raise LabPoseError("invalid_torso_direction")
    lean = math.degrees(math.atan2(abs(dx), dy))
    if not 20 <= lean <= 65:
        raise LabPoseError("insufficient_or_extreme_projected_lean")
    shoulder_span = math.dist(joints[2][:2], joints[5][:2])
    wrist_span = math.dist(joints[4][:2], joints[7][:2])
    if shoulder_span < 4 or wrist_span < .4 * shoulder_span:
        raise LabPoseError("palms_not_separately_localized")
    if any(joints[i][1] <= hips[1] + .12 * height or
           joints[i][1] >= height - .015 * height for i in (10, 13)):
        raise LabPoseError("ankles_cropped_or_not_below_hips")
    if any(joints[i][1] > hips[1] for i in (4, 7)):
        raise LabPoseError("wrists_below_hips")
    return {
        "projected_torso_lean_from_vertical_deg": round(lean, 2),
        "wrist_span_px": round(wrist_span, 2),
        "shoulder_span_px": round(shoulder_span, 2),
        "both_wrists_and_ankles_detected": True,
        "geometry_only_not_contact_proof": True,
    }


def build_proposal(root, pack_file, reference_id, photo_observation, trusted_hashes):
    root = Path(root).resolve()
    pack_file = Path(pack_file).resolve()
    if not isinstance(trusted_hashes, dict) or set(trusted_hashes) != set(PINNED_CG03_01):
        raise LabPoseError("trusted_hash_set_required")
    if not isinstance(photo_observation, dict):
        raise LabPoseError("missing_photo_observation")
    if not photo_observation.get("reviewer") or not photo_observation.get("reviewed_at"):
        raise LabPoseError("missing_photo_observer")
    if any(photo_observation.get(key) is not True
           for key in REQUIRED_PHOTO_OBSERVATIONS):
        raise LabPoseError("source_photo_not_observable")
    entries = json.loads(_path(root, "manifest.json").read_text())
    matches = [x for x in entries if x.get("id") == reference_id]
    if len(matches) != 1:
        raise LabPoseError("reference_not_unique")
    item = matches[0]
    if item.get("status") != "draft" or item.get("approved") is not False:
        raise LabPoseError("not_an_unapproved_draft")
    if item.get("camera") != "rear" or item.get("action") != "palms_on_wall":
        raise LabPoseError("wrong_camera_or_action")
    if item.get("extraction_status") != "generated" or item.get("body_joints_confident") != 18:
        raise LabPoseError("incomplete_source_extraction")
    if item.get("usage_scope") != "private_local_pose_review_no_photo_redistribution":
        raise LabPoseError("unsafe_reference_scope")
    reference = _path(root, item["reference"])
    guide = _path(root, item["guide"])
    extraction = _path(root, item["keypoints"])
    if _sha(reference) != item.get("reference_sha256"):
        raise LabPoseError("reference_hash_mismatch")
    if _sha(guide) != item.get("guide_sha256"):
        raise LabPoseError("guide_hash_mismatch")
    with Image.open(reference) as image:
        if image.size != tuple(item["dimensions"]):
            raise LabPoseError("reference_dimensions_mismatch")
        width, height = image.size
        image.verify()
    with Image.open(guide) as image:
        if image.size != (1216, 704):
            raise LabPoseError("invalid_guide_dimensions")
        image.verify()
    geometry = _geometry(_joints(json.loads(extraction.read_text())), width, height)
    pack = json.loads(pack_file.read_text())
    if pack.get("mode") != "first_attempt_only":
        raise LabPoseError("pack_not_first_attempt")
    cases = [case for case in pack.get("cases", []) if case.get("id") == "CG-03"]
    if len(cases) != 1:
        raise LabPoseError("missing_or_duplicate_cg03")
    case = cases[0]
    if case.get("type") != "cg" or case.get("canvas") != [1024, 592]:
        raise LabPoseError("unexpected_case_contract")
    prompt = case.get("prompt", "").lower()
    expected = " ".join(case.get("expected", [])).lower()
    if not all(token in prompt for token in
               ("three-quarter rear", "both open hands", "stone wall", "boots")):
        raise LabPoseError("camera_contact_or_boots_not_in_contract")
    if not all(token in expected for token in ("both palms", "forward body lean")):
        raise LabPoseError("mandatory_expected_missing")
    # Bind the observer's visual statements to the exact *reviewed photo* and
    # independently pin all actual test inputs against the frozen baseline.
    # Checking only each manifest entry against its own mutable hash is weak:
    # changing BOTH bytes and metadata would otherwise silently pass.
    actual_hashes = {
        "reference": _sha(reference),
        "guide": _sha(guide),
        "extraction": _sha(extraction),
        "pack": _sha(pack_file),
    }
    if photo_observation.get("reference_sha256") != actual_hashes["reference"]:
        raise LabPoseError("source_photo_observation_hash_mismatch")
    for name, digest in actual_hashes.items():
        if (not isinstance(trusted_hashes[name], str) or
                len(trusted_hashes[name]) != 64 or
                trusted_hashes[name] != digest):
            raise LabPoseError("pinned_" + name + "_hash_mismatch")
    return {
        "schema": "web-vn-lab-pose-proposal-v1",
        "status": "experimental_unapproved",
        "reference_id": reference_id,
        "source_reference_sha256": _sha(reference),
        "source_guide_sha256": _sha(guide),
        "source_extraction_sha256": _sha(extraction),
        "source_manifest_sha256": _sha(root / "manifest.json"),
        "scene_pack_sha256": _sha(pack_file),
        "scene_case": "CG-03",
        "scene_seed": case["seed"],
        "scene_canvas": case["canvas"],
        "target_camera": "rear_three_quarter",
        "target_action": "both_palms_on_vertical_wall_forward_lean",
        "source_camera_manifest": item["camera"],
        "source_license": item.get("source_license", "unknown"),
        "source_footwear_not_target_wardrobe_proof": True,
        "source_photo_observation": {
            "reviewer": photo_observation["reviewer"],
            "reviewed_at": photo_observation["reviewed_at"],
            "reference_sha256": actual_hashes["reference"],
            "checks": {k: True for k in REQUIRED_PHOTO_OBSERVATIONS},
            "scope": "source_photo_only_not_generated_result",
        },
        "geometry": geometry,
        "one_changed_factor": "pose_conditioning_off_to_on",
        "held_fixed": ["scene_contract", "seed", "model", "sampler", "resolution",
                       "identity", "outfit", "prompt_text", "QA"],
        "first_shot_v1_unchanged": True,
        "gpu_job_budget": 1,
        "production_approved": False,
        "gpu_authorized": False,
        "broker_enforcement": "NOT_VERIFIED",
        "native_pose_graph_compatibility": "NOT_VERIFIED",
        "generated_image_g2": "NOT_REVIEWED",
        "note": "Photo/DWPose geometry does not prove generated 3D contact; no submit or publish.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--reference-id", default="wall_push_rear_oblique_01")
    parser.add_argument("--photo-observation", required=True,
                        help="Private JSON with observer/time and five true source-photo observations")
    parser.add_argument("--output", required=True, help="Private local JSON destination, not GitHub")
    args = parser.parse_args()
    observation = json.loads(Path(args.photo_observation).read_text())
    if args.reference_id != "wall_push_rear_oblique_01":
        raise LabPoseError("reference_not_pinned_for_this_experiment")
    result = build_proposal(args.root, args.pack, args.reference_id,
                            observation, PINNED_CG03_01)
    output = Path(args.output)
    if output.exists():
        raise LabPoseError("refuse_overwrite")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(output.parent.stat().st_mode) & 0o077:
        raise LabPoseError("unsafe_output_dir_permissions")
    # Atomic exclusive creation with 0600 from the first instant; no public
    # readability window and no following an existing output symlink.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("LAB_PROPOSAL_ONLY", result["reference_id"],
          result["source_guide_sha256"], "GPU_NOT_AUTHORIZED")


if __name__ == "__main__":
    main()
