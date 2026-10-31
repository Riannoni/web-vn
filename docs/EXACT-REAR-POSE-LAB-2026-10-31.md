# #77 — CG-03 rear three-quarter wall-contact photo/guide audit (2026-10-31)

**Status:** SOURCE-ONLY LAB PREFLIGHT + private proposal; **not a production pose approval, not a GPU render, not a G2 pass**. Read root `AGENTS.md` and full `docs/DEVELOPMENT-AND-TESTING.md` first. This is an independently scoped response to [#77](https://github.com/Riannoni/web-vn/issues/77), and does not modify the approved pose manifest or active game.

## Actual original-source inspection on gaming PC

Read **original source photographs and corresponding original guide PNGs**, not filenames or model captions, from `~/.local/share/mcp-vn/pose-references-v1`. Cropped original-photo closeups were also visually inspected for palms. Source hashes were recomputed against the installed manifest. Private photographs and derived PNGs are **not in GitHub** because third-party licensing is unverified.

| Installed ID | Source photo, actual visual observations | DWPose and verdict |
| --- | --- | --- |
| `wall_push_rear_oblique_01` | Rear three-quarter / oblique back; **two separate open palms visibly pressed against a vertical wall** in the *source photo*, forward torso lean, both shoes/feet visible. This is the strongest source for the intended view. | All **18/18** COCO joints confident; projected neck→hip lean **37.02° from vertical**; wrist separation **99.46 px**, shoulder separation **62.37 px**. Existing guide is **DRAFT, unapproved**; usable as a *photo-grounded experimental* conditioning candidate only. |
| `wall_push_rear_oblique_02` | Rear-oblique photo and forward lean, both feet visible; one palm is visible but the other palm/contact is **not independently observable** in the inspected crop. | **17/18** joints confident; one wrist has zero confidence. Reject as the two-palm exact-view candidate; do not infer the missing hand from a caption. |
| `wall_push_correct_side_a` | Both palms on wall, feet visible, but **SIDE camera**, not rear three-quarter. | **18/18**; approved only for side-view pose geometry after prior A/B. **Must never silently substitute** for CG-03. |

Actual local immutable SHA-256:
- `rear_oblique_01` reference JPEG: `730b51efb109b5c6834ada6699d43141f17111f8731f05ea5416bcd9d71bc631`
- `rear_oblique_01` DWPose guide PNG: `7391e30022bc83c89a4d5105c1efd5ce939d9cd460648a0ff7aa6121109793a2`
- `rear_oblique_01` extraction JSON: `d506a43e308cc8f9a30885f74223a35689d5b95101d289ad4b898edb10e1018b`
- `rear_oblique_02` reference JPEG: `852e939c3b781712a5bbfe96cc06b27c6f4c2a345f26df1c2d0d25457ed00e1d`
- `rear_oblique_02` DWPose guide PNG: `2a5d7e2a734831f70601421c326cae1750b5506f5b7b8a4dba1ea70102aebea7`

**Footwear accuracy:** the source photograph shows **shoes/sneakers, not the character's required tall boots**. The source-photo check is strictly `both_feet_visible`; the generated CG must independently satisfy the **boots/wardrobe** contract. Source clothing never establishes canonical outfit compliance.

**Critical distinction:** the original *photograph* shows physical hand-wall contact; the DWPose guide is **2D skeleton coordinates**, so neither it nor projected wrist proximity proves that a *future generated* CG has 3D palm contact. Golden must independently review that exact original Comfy PNG, including camera, both palms, boots, identity, outfit and masonry. A mandatory `unobservable` remains FAIL/UNVERIFIED.

## Existing grounded candidate, no invented source photo

Use `wall_push_rear_oblique_01`, not a newly invented photo or a replacement side-camera image. Its extraction was produced with installed Comfy `DWPreprocessor` (YOLOX-L bbox, `dw-ll_ucoco_384.onnx`, body/hand enabled) and `SavePoseKpsAsJsonFile` per `worker/pose_reference_pipeline.py`; existing guide is a 1216×704 PNG and its original JPEG is 1200×800. The intended CG-03 canvas is **1024×592**; before any GPU run the Renderer must verify **native model/Union pose-conditioning compatibility**, graph node wiring, and the exact no-crop guide resize/transform/hash. Do not assume SDXL ControlNet nodes are compatible with Z-Image.

A private metadata-only proposal was generated **on the gaming PC** under the existing private first-shot lab root (`pose77/CG03-R15-rear-oblique-01-experimental-v2.json`, mode 0600). Its SHA-256 is `7f16e77c173a16cbc02a7483383aeeff536178fc010997ba885b80a3ebf3bc0f`; public `pack-v1.json` SHA-256 is `aa5a8f94859ff6b5e8c99386757cc9fccd1fa5e88a2fdd3e6970e556f8438910`. The proposal explicitly says `experimental_unapproved`, `gpu_authorized=false`, `broker_enforcement=NOT_VERIFIED`, `generated_image_g2=NOT_REVIEWED`; no private reference or image is copied to GitHub. The earlier v1 metadata proposal incorrectly called the photo footwear `both_boots_visible`; it is retained only under the private `pose77/superseded/` audit directory and **must not be used**. v2 correctly records `both_feet_visible` and `source_footwear_not_target_wardrobe_proof=true`. **The existing local manifest remains DRAFT/approved=false** for both rear-oblique entries.

The source-only script `scripts/first_shot/lab_pose_reference.py` performs SHA-bound photo/guide/extraction/manifest checks, exact action+camera/contract matching, full joint coverage, forward-lean/wrist/ankle geometry, explicit source-photo observation and no-replace private JSON proposal. It deliberately **does not call Comfy, sign approval, enqueue a task, alter the production selector, or publish anything**. Its geometry checks are conservative prerequisites, not proof of actual contact.

## Falsifiable next A/B (for Chief/Renderer, not yet authorized)

1. Independent Broker Reviewer and Chief first verify/deploy **single-owner Comfy enforcement**, including OS-level denial of direct `/prompt` bypass, crash/restart semantics, and rollback. A queue snapshot or `flock` alone is not proof. PR #78 was still draft/source-only during this audit.
2. Chief opens a **new R-15** (not resurrecting R-14/G-11) with dependencies on the exact broker rollout, R-13 baseline and S-14; use `experimental_unapproved` rather than circular preapproval. One controlled **disposable** CG-03 A/B with same frozen seed `202610310105`, scene contract, model, sampler, prompt, identity, wardrobe, QA, resolution; change only pose conditioning. Record any unavoidable workflow differences and exact guide transform. Do **not** rerun R-13 prompt `7b3b344b-fd8c-4068-8bd6-e541266ec174`.
3. A single broker-fenced GPU submission **at most one candidate**; exact Comfy prompt ID, final original PNG SHA, source/graph SHA, seed, first-attempt index, full timings, no publish. If native Union graph cannot safely consume this guide, report `BLOCKED_INCOMPATIBLE`, **not** a substitute prompt-only reroll.
4. Golden independently inspects the original PNG against the exact private scene and canonical references. The A/B hypothesis is **falsified** if the view becomes side/frontal, forward lean disappears, either palm contact is violated/unobservable, either boot is cropped, or other mandatory facts fail. Even if pose succeeds, canonical identity/wardrobe are separate mandatory G2 gates. STOP after 2–3 causally identical failures.

**Known implementation gap:** current `scripts/first_shot/autonomous_dispatch.py` accepts only `factor=prompt_text`. It **cannot** safely run this `pose_conditioning` A/B without a separately reviewed typed factor + compatible graph implementation and broker-fenced integration. Do not smuggle guide changes into `prompt_text` or claim this preflight file authorizes GPU work.

## Source-only tests and status

The PC isolated Git checkout at commit `04d9fe63806fbeaa92a77d676e933d43dcd1f433` passed **13/13 synthetic, networkless tests**: exact rear view, no side substitution, no missing wrist, no cropped ankle, no upright torso, both source palms observable, exact CG-03 contract, source/guide SHA, path traversal, draft-only status, first-attempt pack and restricted photo scope. The final CLI also wrote a private temporary proposal with file mode **0600** and passed `py_compile` and `git diff --check`. The real installed `rear_oblique_01` + frozen pack produced the private proposal with geometry and hashes above. **No GPU submission, no model/service restart, no canonical save mutation, no new generated G2 evidence.** This is a source/provenance preflight milestone only.

## 2026-10-31 follow-up: immutable input provenance v3 (later independent run)

The source-only preflight previously verified the JPEG and pose guide against their **mutable manifest** but merely reported the current `pack-v1.json` SHA. That was insufficient for a controlled one-factor A/B: replacing *both* a source file and its manifest hash, or editing seed in the pack, could silently change the input while the output claimed `held_fixed`. The now-updated draft PR #80 closes this source-integrity gap **without any GPU use**:

- One explicitly pinned CG-03 v1 input set: original JPEG SHA `730b51efb109b5c6834ada6699d43141f17111f8731f05ea5416bcd9d71bc631`, guide SHA `7391e30022bc83c89a4d5105c1efd5ce939d9cd460648a0ff7aa6121109793a2`, original extraction SHA `d506a43e308cc8f9a30885f74223a35689d5b95101d289ad4b898edb10e1018b`, frozen pack SHA `aa5a8f94859ff6b5e8c99386757cc9fccd1fa5e88a2fdd3e6970e556f8438910`. Replacing source+manifest, guide+manifest, extraction-only or pack seed now FAILs.
- The independent source-photo observer record now includes `reference_sha256` matching **the actual inspected JPEG**. Otherwise the preflight rejects `source_photo_observation_hash_mismatch`. The field prevents accidentally applying old observation booleans to another photo; it does not cryptographically prove observer independence or validate future generated hand-wall contact.
- Existing `v2` metadata is superseded as an operational proposal by **private v3**; v1 remains quarantined for the footwear error. Latest private v3 metadata SHA256 is `b3190f9ee215f57d23c6ca12a342e73cbed9149f8476956759351fec48e5c0f5` and its matching independent source-photo observation SHA256 is `36665b9fa866e872d9c3d2807259dcd2da35f67615c8a14100bd06de3d43fde5`. Both files are 0600 in the PC's 0700 lab directory, never uploaded to GitHub.
- Re-read actual original JPEGs and the corresponding 1216×704 guide PNGs: `_01` visibly supports a rear oblique view, two distinct wall palms and forward body lean; `_02` still lacks a separately observable second palm. The photo subject wears sneakers, not the character's tall boots. This is **source-photo geometry only**, not a generated G2 PASS.
- Isolated gaming-PC GitHub checkout SHA `fba7df6c20095e835df97e77017c4980b0ca1dc5`: Python syntax, `git diff --check`, **18/18 source-only tests PASS**. CLI validated the real installed source bytes and created v3 `experimental_unapproved` with `GPU_NOT_AUTHORIZED`. No changes to Comfy, production selector, active game, canonical save or manifest; G1/G2/G3 unchanged.

Chief must independently review the latest **exact** PR #80 SHA and these five added negative cases before accepting its lab input provenance. A separate reviewed native Z-Image Union pose-conditioning graph and a **deployed and technically enforced single-owner broker** remain prerequisites. Once those exist, Renderer may request ONE disposable R-15 A/B, not an R-13 resubmit; Golden must review the new exact original PNG for actual 3D contact, identity and boots. No new GPU output was produced here.
