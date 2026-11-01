"""Private content-addressed face PNG store; never expose source bytes in Comfy graphs.

A SHA-256 key is the only untrusted graph input. The root is trusted
out-of-band configuration and must be a private pre-existing directory.
This module does not authenticate the creation-time actor/outfit/source.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import secrets
import stat

MAX_PNG_BYTES = 12_000_000
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _require_sha(value):
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise ValueError("pinned_face_invalid_sha")
    return value


def _open_private_store(root):
    if not isinstance(root, (str, os.PathLike)) or not root:
        raise ValueError("pinned_face_store_unconfigured")
    path = Path(root)
    parts = path.parts
    if not path.is_absolute() or len(parts) < 2 or any(p in ("", ".", "..") for p in parts[1:]):
        raise ValueError("pinned_face_store_unsafe_path")
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", dir_flags)
    try:
        for comp in parts[1:]:
            new_fd = os.open(comp, dir_flags, dir_fd=fd)
            os.close(fd)
            fd = new_fd
        st = os.fstat(fd)
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) & 0o077):
            raise ValueError("pinned_face_store_not_private")
        return fd
    except Exception:
        os.close(fd)
        raise


def _read_from_fd(directory_fd, sha):
    _require_sha(sha)
    try:
        fd = os.open(sha + ".png", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                     dir_fd=directory_fd)
    except OSError as exc:
        raise ValueError("pinned_face_missing_or_unsafe_store_file") from exc
    try:
        st = os.fstat(fd)
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) & 0o077
                or not 0 < st.st_size <= MAX_PNG_BYTES):
            raise ValueError("pinned_face_missing_or_unsafe_store_file")
        buf = []
        remaining = MAX_PNG_BYTES + 1
        while remaining:
            block = os.read(fd, min(65536, remaining))
            if not block:
                break
            buf.append(block)
            remaining -= len(block)
        raw = b"".join(buf)
        if not raw or len(raw) > MAX_PNG_BYTES:
            raise ValueError("pinned_face_missing_or_unsafe_store_file")
    finally:
        os.close(fd)
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("pinned_face_sha_mismatch")
    return raw


def read_pinned_store(sha, *, root=None):
    """Read the exact approved bytes, never paths supplied by the graph."""
    _require_sha(sha)
    if root is None:
        root = os.environ.get("WEB_VN_PINNED_FACE_DIR")
    try:
        directory_fd = _open_private_store(root)
    except OSError as exc:
        raise ValueError("pinned_face_store_unavailable") from exc
    try:
        return _read_from_fd(directory_fd, sha)
    finally:
        os.close(directory_fd)


def stage_pinned_store(raw, sha, *, root):
    """Write a private exclusive content-addressed file, never replacing it.

    Intended only for the single GPU Lab owner AFTER source/GPU gates.
    No node installation or GPU operation is performed here.
    """
    _require_sha(sha)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_PNG_BYTES:
        raise ValueError("pinned_face_invalid_store_bytes")
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("pinned_face_sha_mismatch")
    try:
        directory_fd = _open_private_store(root)
    except OSError as exc:
        raise ValueError("pinned_face_store_unavailable") from exc
    tmp = ".staging-" + secrets.token_hex(16)
    try:
        tmp_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                         dir_fd=directory_fd)
        try:
            offset = 0
            while offset < len(raw):
                n = os.write(tmp_fd, raw[offset:])
                if n < 1:
                    raise OSError("short store write")
                offset += n
            os.fchmod(tmp_fd, 0o400)
            os.fsync(tmp_fd)
        finally:
            os.close(tmp_fd)
        try:
            try:
                os.link(tmp, sha + ".png", src_dir_fd=directory_fd,
                        dst_dir_fd=directory_fd, follow_symlinks=False)
                os.fsync(directory_fd)
            except FileExistsError:
                pass
        finally:
            os.unlink(tmp, dir_fd=directory_fd)
        staged = _read_from_fd(directory_fd, sha)
        if staged != raw:
            raise ValueError("pinned_face_store_existing_bytes_conflict")
        return sha
    finally:
        os.close(directory_fd)
