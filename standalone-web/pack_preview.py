"""Fail-closed read-only Mira/Max quality-pack views for authenticated Model Lab.

This module never generates, exports, publishes or accepts images. The allowlist is a
private on-disk file created after independent verification of exact original hashes.
An absent manifest disables this preview entirely.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import struct
import zlib
from pathlib import Path

PACK_NAME = 'mira-quality-pack-20261101-v1'
ALLOWED_DIRS = frozenset((
    PACK_NAME,
    'integration-mira-assembly-20261101-v1',
    'integration-mira-v3-adoption-20261101-v1',
))
ID_PATTERN = re.compile(r'(?:BG|MIRA_[123]|MAX_[123]|VN_[123]|CG_[123])\Z')
SHA_PATTERN = re.compile(r'[0-9a-f]{64}\Z')
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_PNG_BYTES = 32 * 1024 * 1024


class PreviewError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def _private_file(path: Path, *, allow_missing: bool = False) -> bytes:
    try:
        if path.is_symlink():
            raise PreviewError('Symlink disallowed')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    except FileNotFoundError:
        if allow_missing:
            raise PreviewError('Preview is not configured', 404) from None
        raise PreviewError('Private input is missing', 409) from None
    except OSError:
        raise PreviewError('Private input is unavailable', 409) from None
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
            raise PreviewError('Private input permissions invalid')
        if details.st_size > MAX_PNG_BYTES or details.st_size == 0:
            raise PreviewError('Private input size invalid')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(MAX_PNG_BYTES + 1)
        if len(data) > MAX_PNG_BYTES:
            raise PreviewError('Private input too large')
        return data
    finally:
        os.close(fd)


def _png_info(data: bytes) -> tuple[int, int, int]:
    if not data.startswith(PNG_SIGNATURE):
        raise PreviewError('Not a PNG')
    offset = len(PNG_SIGNATURE)
    head = None
    compressed = bytearray()
    seen_end = False
    while offset + 12 <= len(data):
        size = struct.unpack_from('>I', data, offset)[0]
        if size > MAX_PNG_BYTES or offset + 12 + size > len(data):
            raise PreviewError('Invalid PNG chunk length')
        tag = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        crc = struct.unpack_from('>I', data, offset + 8 + size)[0]
        if zlib.crc32(tag + payload) & 0xffffffff != crc:
            raise PreviewError('Invalid PNG checksum')
        if head is None:
            if tag != b'IHDR' or size != 13:
                raise PreviewError('Missing PNG header')
            width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
            if width < 1 or height < 1 or depth != 8 or color not in (2, 6) or compression or filtering or interlace:
                raise PreviewError('Unexpected PNG format')
            head = (width, height, color)
        elif tag == b'IDAT':
            compressed.extend(payload)
        elif tag == b'IEND':
            if size != 0 or not compressed or offset + 12 != len(data):
                raise PreviewError('Invalid PNG end')
            seen_end = True
            break
        offset += 12 + size
    if not seen_end or head is None:
        raise PreviewError('Incomplete PNG')
    width, height, color = head
    expected = height * (1 + width * (4 if color == 6 else 3))
    if expected > 100 * 1024 * 1024:
        raise PreviewError('Decoded image too large')
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error:
        raise PreviewError('PNG pixels cannot be decoded') from None
    if len(decoded) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise PreviewError('PNG pixel dimensions do not match')
    stride = 1 + width * (4 if color == 6 else 3)
    if any(decoded[i * stride] > 4 for i in range(height)):
        raise PreviewError('Invalid PNG scanline filter')
    return head


class PackPreview:
    def __init__(self, base: Path | None = None):
        self.base = (base or Path.home() / '.local/share/web-vn-native-team/first-shot-lab-20261031').resolve()
        self.pack = self.base / PACK_NAME
        self.index = self.pack / 'golden-evidence-index.json'
        self.config = self.pack / 'private-preview-allowlist-v1.json'

    def _manifest(self) -> dict:
        raw = _private_file(self.config, allow_missing=True)
        try:
            doc = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PreviewError('Invalid preview allowlist') from None
        if not isinstance(doc, dict) or doc.get('schema') != 1:
            raise PreviewError('Unrecognized preview allowlist')
        digest = doc.get('source_index_sha256')
        assets = doc.get('assets')
        if not isinstance(digest, str) or not SHA_PATTERN.fullmatch(digest):
            raise PreviewError('Missing immutable index hash')
        if not isinstance(assets, dict) or not 1 <= len(assets) <= 13:
            raise PreviewError('Invalid asset allowlist')
        if hashlib.sha256(_private_file(self.index)).hexdigest() != digest:
            raise PreviewError('Stale golden evidence index')
        for asset_id, item in assets.items():
            if not isinstance(asset_id, str) or not ID_PATTERN.fullmatch(asset_id) or not isinstance(item, dict):
                raise PreviewError('Unexpected asset binding')
            kind = 'sprite' if asset_id.startswith(('MIRA_', 'MAX_')) else ('composite' if asset_id.startswith('VN_') else 'background' if asset_id == 'BG' else 'cg')
            if item.get('kind') != kind or not isinstance(item.get('file'), str):
                raise PreviewError('Invalid asset role')
            if not isinstance(item.get('sha256'), str) or not SHA_PATTERN.fullmatch(item['sha256']):
                raise PreviewError('Invalid asset hash')
            if type(item.get('width')) is not int or type(item.get('height')) is not int or not (1 <= item['width'] <= 4096 and 1 <= item['height'] <= 4096):
                raise PreviewError('Invalid dimensions')
        return assets

    def visible_ids(self) -> list[str]:
        return sorted(self._manifest())

    def image_bytes(self, asset_id: str) -> bytes:
        if not isinstance(asset_id, str) or not ID_PATTERN.fullmatch(asset_id):
            raise PreviewError('Unknown pack asset', 404)
        item = self._manifest().get(asset_id)
        if item is None:
            raise PreviewError('Pack asset is not ready', 404)
        # Only exact local paths under the new Mira pack/integration areas are allowed;
        # importantly, legacy denied H2 images cannot be mapped here.
        relative = Path(item['file'])
        if relative.is_absolute() or not relative.parts or relative.parts[0] not in ALLOWED_DIRS or '..' in relative.parts:
            raise PreviewError('Asset location is outside the pack')
        path = self.base / relative
        try:
            if not path.resolve(strict=True).is_relative_to(self.base / relative.parts[0]):
                raise PreviewError('Asset escapes the pinned pack directory')
        except OSError:
            raise PreviewError('Asset not accessible') from None
        blob = _private_file(path)
        if hashlib.sha256(blob).hexdigest() != item['sha256']:
            raise PreviewError('Asset hash mismatch')
        width, height, color = _png_info(blob)
        if (width, height) != (item['width'], item['height']):
            raise PreviewError('Asset dimensions mismatch')
        if asset_id.startswith(('MIRA_', 'MAX_')) and color != 6:
            raise PreviewError('Sprites require RGBA PNG')
        return blob
