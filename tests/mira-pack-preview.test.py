"""Focused fail-closed tests for pinned private Mira pack previews."""
import hashlib
import json
import os
import stat
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'standalone-web'))
from pack_preview import PreviewError, PackPreview


def png(width=4, height=3, rgba=True):
    typ = 6 if rgba else 2
    ihdr = struct.pack('>IIBBBBB', width, height, 8, typ, 0, 0, 0)
    # One simple scanline per row. Only standard 8-bit RGB/RGBA.
    stride = width * (4 if rgba else 3)
    data = b''.join(b'\0' + b'\x7f' * stride for _ in range(height))
    def chunk(name, body):
        return struct.pack('>I', len(body)) + name + body + struct.pack('>I', zlib.crc32(name + body) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(data)) + chunk(b'IEND', b'')


class PackPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.pack = self.base / 'mira-quality-pack-20261101-v1'
        self.pack.mkdir(mode=0o700)
        self.original = self.pack / 'VN_1.png'
        self.original.write_bytes(png())
        self.original.chmod(0o400)
        self.index = self.pack / 'golden-evidence-index.json'
        self.index.write_text('{}')
        self.index.chmod(0o400)
        self.manifest = self.pack / 'private-preview-allowlist-v1.json'
        self.source = {
            'schema': 1,
            'source_index_sha256': hashlib.sha256(self.index.read_bytes()).hexdigest(),
            'assets': {
                'VN_1': {'file': 'mira-quality-pack-20261101-v1/VN_1.png',
                         'sha256': hashlib.sha256(self.original.read_bytes()).hexdigest(),
                         'width': 4, 'height': 3, 'kind': 'composite'},
            },
        }
        self.write_manifest()
        self.reader = PackPreview(self.base)

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.source))
        self.manifest.chmod(0o400)

    def test_exact_composite_and_metadata(self):
        self.assertEqual(self.reader.image_bytes('VN_1'), self.original.read_bytes())
        self.assertEqual(self.reader.visible_ids(), ['VN_1'])

    def test_unknown_ids_and_traversal_fail_closed(self):
        for name in ('VN_2', '../VN_1', '../../etc/passwd', 'VN_1/../../x', '', 'CG_3'):
            with self.subTest(name=name), self.assertRaises(PreviewError) as caught:
                self.reader.image_bytes(name)
            self.assertEqual(caught.exception.status, 404)

    def test_stale_index_fails_closed(self):
        self.index.write_text('{"changed":true}')
        with self.assertRaises(PreviewError) as caught:
            self.reader.image_bytes('VN_1')
        self.assertEqual(caught.exception.status, 409)

    def test_file_bytes_modified_fails_closed(self):
        self.original.chmod(0o600)
        self.original.write_bytes(png(width=5))
        self.original.chmod(0o400)
        with self.assertRaises(PreviewError) as caught:
            self.reader.image_bytes('VN_1')
        self.assertEqual(caught.exception.status, 409)

    def test_symlink_outside_pack_root_fails_closed(self):
        target = self.base.parent / ('test-preview-secret-' + self.base.name)
        target.write_bytes(png())
        self.addCleanup(lambda: target.unlink(missing_ok=True))
        self.original.unlink()
        self.original.symlink_to(target)
        with self.assertRaises(PreviewError):
            self.reader.image_bytes('VN_1')

    def test_reject_old_h2_source_even_if_locally_present(self):
        forbidden = self.base / 'old-h2-experiment'
        forbidden.mkdir()
        (forbidden / 'output.png').write_bytes(png())
        self.source['assets']['VN_1']['file'] = 'old-h2-experiment/output.png'
        self.source['assets']['VN_1']['sha256'] = hashlib.sha256((forbidden / 'output.png').read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaises(PreviewError):
            self.reader.image_bytes('VN_1')

    def test_sprite_requires_rgba(self):
        self.source['assets'] = {
            'MIRA_1': {'file': 'mira-quality-pack-20261101-v1/VN_1.png',
                       'sha256': hashlib.sha256(self.original.read_bytes()).hexdigest(),
                       'width': 4, 'height': 3, 'kind': 'sprite'},
        }
        self.write_manifest()
        # Valid RGBA is a technical pass; RGB as a sprite must fail.
        self.assertEqual(self.reader.image_bytes('MIRA_1'), self.original.read_bytes())
        self.original.chmod(0o600)
        self.original.write_bytes(png(rgba=False))
        self.original.chmod(0o400)
        self.source['assets']['MIRA_1']['sha256'] = hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaises(PreviewError) as caught:
            self.reader.image_bytes('MIRA_1')
        self.assertEqual(caught.exception.status, 409)

    def test_manifest_cannot_be_world_writable(self):
        self.manifest.chmod(0o666)
        with self.assertRaises(PreviewError):
            self.reader.visible_ids()

    def test_manifest_unknown_kind_fails_closed(self):
        self.source['assets']['VN_1']['kind'] = 'other'
        self.write_manifest()
        with self.assertRaises(PreviewError):
            self.reader.image_bytes('VN_1')

    def test_image_png_crc_invalidation_fails_closed(self):
        self.original.chmod(0o600)
        raw = bytearray(self.original.read_bytes())
        raw[-9] ^= 3
        self.original.write_bytes(raw)
        self.original.chmod(0o400)
        self.source['assets']['VN_1']['sha256'] = hashlib.sha256(self.original.read_bytes()).hexdigest()
        self.write_manifest()
        with self.assertRaises(PreviewError):
            self.reader.image_bytes('VN_1')


if __name__ == '__main__':
    unittest.main()
