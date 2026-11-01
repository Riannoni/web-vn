#!/usr/bin/env python3
"""One private, pinned sprite assess() call; no generation, publication or retries."""
import argparse
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

sys.dont_write_bytecode = True


def absolute(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("absolute paths required")
    return path.resolve()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pinned(item):
    path = absolute(item["path"])
    data = path.read_bytes()
    if sha(data) != item["sha256"]:
        raise ValueError("input SHA256 mismatch: " + str(path))
    return data


def blocked(*args, **kwargs):
    raise RuntimeError("generation/publication/non-judge operation prohibited")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("worker", "dependency-dir", "case", "output-root"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    worker_path, deps = absolute(args.worker), absolute(args.dependency_dir)
    case_bytes = absolute(args.case).read_bytes()
    case = json.loads(case_bytes)
    worker_bytes = pinned({"path": str(worker_path), "sha256": case["worker_sha256"]})
    raw, job_bytes = pinned(case["original"]), pinned(case["source_job"])
    job = json.loads(job_bytes)
    if job.get("kind") != "sprite" or not isinstance(job.get("spec"), dict):
        raise ValueError("genuine sprite job with spec required; no kind/spec rewriting")
    face_id = job["spec"].get("face_asset")
    if bool(face_id) != bool(case.get("face")):
        raise ValueError("bind an authentic face iff the source job requires one")
    face_bytes = pinned(case["face"]) if face_id else None
    background_bytes = None if case["background"] == "NONE" else pinned(case["background"])
    cache = absolute(case["u2net_home"])
    model = cache / "isnet-general-use.onnx"
    if not deps.is_dir() or not model.is_file() or model.stat().st_size == 0:
        raise ValueError("existing sibling modules and cached rembg model required")
    vision = case["vision_url"].rstrip("/")
    url = urlsplit(vision)
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
            or not url.port or url.path or url.query or url.fragment or url.username):
        raise ValueError("explicit numeric loopback vision origin and port required")
    output = absolute(args.output_root)
    os.umask(0o077)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)  # Existing means no replay.
    def save(name, value):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    save("started.json", {"status": "started", "pid": os.getpid(), "utc_epoch": time.time(),
         "case_sha256": sha(case_bytes), "worker_sha256": sha(worker_bytes),
         "original_sha256": sha(raw), "source_job_sha256": sha(job_bytes)})
    # Enforce network bounds before importing worker/rembg; never install a missing model.
    def audit(event, values):
        if event == "socket.connect":
            address = values[1]
            if not isinstance(address, tuple) or address[:2] != (url.hostname, url.port):
                blocked()
        if event == "socket.getaddrinfo" and values[:2] != (url.hostname, url.port):
            blocked()
        if event in ("subprocess.Popen", "os.system", "socket.sendto"):
            blocked()
    sys.addaudithook(audit)
    os.environ.update(VN_WORKER_TOKEN="private-cpu-diagnostic-no-publish",
        VN_VISION_QA="1", VN_VISION_URL=vision, U2NET_HOME=str(cache),
        CUDA_VISIBLE_DEVICES="", HIP_VISIBLE_DEVICES="", ROCR_VISIBLE_DEVICES="")
    started = time.monotonic()
    try:
        from PIL import Image
        def decode(data):
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                return source.copy()
        decode(raw)
        face = decode(face_bytes) if face_bytes else None
        background = decode(background_bytes) if background_bytes else None
        sys.path.insert(0, str(deps))
        spec = importlib.util.spec_from_file_location("sprite_assess_worker", worker_path)
        worker = importlib.util.module_from_spec(spec)
        # Execute exactly the verified bytes, not a second mutable file read.
        exec(compile(worker_bytes, str(worker_path), "exec"), worker.__dict__)
        def request(base, path, method="GET", data=None, headers=None, timeout=15):
            if base != vision or path != "/judge" or method != "POST" or headers:
                blocked()
            connection = http.client.HTTPConnection(url.hostname, url.port,
                                                    timeout=min(45, max(1, timeout)))
            try:
                connection.request("POST", "/judge", json.dumps(data),
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                if response.status != 200:
                    raise ValueError("vision HTTP status " + str(response.status))
                return json.loads(response.read())
            finally:
                connection.close()
        worker.request = request
        worker.fetch_asset = lambda name: face.copy() if face is not None and name == face_id else blocked()
        for name in ("generate_gpu", "run_comfy", "upload_to_comfy", "verify_with_comfy",
                     "finalize", "cpu_scene", "stage", "fail", "main", "urlopen"):
            setattr(worker, name, blocked)
        assess_start = time.monotonic()
        final, result = worker.assess(job, raw, background)
        elapsed = time.monotonic() - assess_start
        with (output / "final.png").open("xb") as stream:
            stream.write(final)
        save("result.json", {"status": "completed", "qa": result, "assess_wall_seconds": elapsed,
             "runner_wall_seconds": time.monotonic()-started, "final_sha256": sha(final),
             "final_bytes": len(final), "worker_sha256": sha(worker_bytes),
             "source_job_sha256": sha(job_bytes), "original_sha256": sha(raw),
             "case_sha256": sha(case_bytes), "independent_g2": "NOT_REVIEWED"})
        print(json.dumps({"status": "completed", "qa_passed": result.get("passed"),
                          "assess_wall_seconds": elapsed, "result_path": str(output/"result.json")}))
    except Exception as exc:
        save("error.json", {"status": "failed_or_partial", "error_type": type(exc).__name__,
                            "error": str(exc)[:2000],
                            "runner_wall_seconds": time.monotonic()-started})
        raise SystemExit("failed_or_partial; inspect private records; do not replay this output root") from None


if __name__ == "__main__":
    main()
