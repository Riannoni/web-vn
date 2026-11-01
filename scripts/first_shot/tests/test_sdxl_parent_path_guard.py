"""Isolated, synthetic private-source ancestor-symlink safety regression."""
import hashlib
import pathlib
import sys
import tempfile
import unittest
HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import sdxl_sprite_factor as sprite
class PinnedDirfdSecurity(unittest.TestCase):
    def test_regular_sha_pinned_file_is_readable(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td).resolve()/'source.json'
            raw=b'{"synthetic":true}'
            p.write_bytes(raw)
            self.assertEqual(sprite._read_pinned(p,hashlib.sha256(raw).hexdigest()),raw)
    def test_leaf_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td).resolve()
            raw=b'{"synthetic":true}'
            genuine=root/'target.json';genuine.write_bytes(raw)
            (root/'source.json').symlink_to(genuine)
            with self.assertRaisesRegex(ValueError,'missing_or_unsafe_private_source'):
                sprite._read_pinned(root/'source.json',hashlib.sha256(raw).hexdigest())
    def test_parent_symlink_rejected_even_if_sha_matches(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td).resolve()
            actual=root/'outside';actual.mkdir()
            raw=b'{"synthetic":true}'
            h=hashlib.sha256(raw).hexdigest()
            (actual/(h+'.json')).write_bytes(raw)
            (root/'private_sources').symlink_to(actual,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'missing_or_unsafe_private_source'):
                sprite._read_pinned(root/'private_sources'/(h+'.json'),h)
    def test_nested_parent_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td).resolve()
            actual=root/'outside';actual.mkdir()
            raw=b'{"synthetic":true}'
            h=hashlib.sha256(raw).hexdigest()
            (actual/(h+'.json')).write_bytes(raw)
            (root/'c').mkdir()
            (root/'c'/'creation_receipts').symlink_to(actual,target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'missing_or_unsafe_private_source'):
                sprite._read_pinned(root/'c'/'creation_receipts'/(h+'.json'),h)
if __name__=='__main__':
    unittest.main()
