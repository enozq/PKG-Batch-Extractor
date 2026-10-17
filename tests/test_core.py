from pathlib import Path
import sys
import struct
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from pkg_batch_extractor.core import (  # noqa: E402
    DISK_SPACE_BUFFER, DISK_SPACE_MULTIPLIER, clean_name, collect_pkgs,
    estimate_required_disk_bytes, format_bytes, next_available_target,
    find_title_id, plan_jobs, read_title_id, scan_folder,
)


class CoreTests(unittest.TestCase):
    @staticmethod
    def _sfo(title_id='CUSA01022'):
        key_table = b'TITLE_ID\0'
        value = title_id.encode('ascii') + b'\0'
        key_base = 36
        data_base = key_base + len(key_table)
        entry = struct.pack('<HHIII', 0, 0x0204, len(value), len(value), 0)
        return struct.pack('<4sIIII', b'\0PSF', 0x101, key_base, data_base, 1) + entry + key_table + value

    def test_title_id_from_param_sfo_and_bad_value(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'param.sfo'
            path.write_bytes(self._sfo())
            self.assertEqual(read_title_id(path), 'CUSA01022')
            self.assertEqual(find_title_id(path.parent), 'CUSA01022')
            path.write_bytes(self._sfo('not-an-id'))
            self.assertIsNone(read_title_id(path))

    def test_clean_name(self):
        self.assertEqual(clean_name('Game<>:"/\\|?*'), 'Game_________')
        self.assertEqual(clean_name('CON'), '_CON')
        self.assertEqual(clean_name('con.txt'), '_con.txt')
        self.assertEqual(clean_name('..'), 'package')
        self.assertEqual(clean_name('hello. '), 'hello')
        self.assertLessEqual(len(clean_name('a' * 200)), 90)

    def test_format_bytes(self):
        self.assertEqual(format_bytes(0), '0 B')
        self.assertEqual(format_bytes(2048), '2.0 KB')
        self.assertEqual(format_bytes(1024 * 1024 * 1024), '1.0 GB')

    def test_disk_space_estimate_uses_package_sizes_and_safety_buffer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a, b = root / 'a.pkg', root / 'b.pkg'
            a.write_bytes(b'12345')
            b.write_bytes(b'1234567')
            jobs = plan_jobs([a, b], root / 'out')
            expected = (a.stat().st_size + b.stat().st_size) * DISK_SPACE_MULTIPLIER + DISK_SPACE_BUFFER
            self.assertEqual(estimate_required_disk_bytes(jobs), expected)

    def test_collect_and_scan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            one = root / 'Game.PKG'
            two = root / 'DLC.pkg'
            junk = root / 'readme.txt'
            for file in (one, two, junk):
                file.write_bytes(b'fake data')
            found = collect_pkgs([one, one, two, junk, root / 'missing.pkg'])
            self.assertEqual(found, [one, two])
            self.assertEqual(set(scan_folder(root)), {one, two})

    def test_output_collision_and_existing_folder(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / 'a' / 'Game.pkg'
            b = root / 'b' / 'Game.pkg'
            a.parent.mkdir()
            b.parent.mkdir()
            a.write_bytes(b'a')
            b.write_bytes(b'b')
            out = root / 'extracted'
            (out / 'Game').mkdir(parents=True)
            jobs = plan_jobs([a, b], out)
            self.assertEqual([j.destination.name for j in jobs], ['Game (2)', 'Game (3)'])
            self.assertEqual(next_available_target(out / 'Game').name, 'Game (2)')
            # Inputs must remain unchanged after path planning.
            self.assertEqual(a.read_bytes(), b'a')

    def test_dangling_symlink_is_never_used_as_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pkg = root / 'Game.pkg'
            pkg.write_bytes(b'pkg')
            out = root / 'output'; out.mkdir()
            link = out / 'Game'
            try:
                link.symlink_to(root / 'nonexistent-folder', target_is_directory=True)
            except (NotImplementedError, OSError):
                self.skipTest('symlink creation unavailable on this OS')
            jobs = plan_jobs([pkg], out)
            self.assertEqual(jobs[0].destination.name, 'Game (2)')
            self.assertEqual(next_available_target(link).name, 'Game (2)')
            self.assertTrue(link.is_symlink())

    def test_casefold_collisions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a, b = root / 'foo.pkg', root / 'FOO.pkg'
            a.write_bytes(b'a')
            b.write_bytes(b'b')
            found = collect_pkgs([a, b])
            self.assertEqual(len(found), 1)


if __name__ == '__main__':
    unittest.main()
