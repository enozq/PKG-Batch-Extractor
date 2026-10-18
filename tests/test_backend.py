from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from pkg_batch_extractor.backend import (  # noqa: E402
    Extractor, application_directory, discover_executable, engine_filenames,
)
from pkg_batch_extractor.settings import load_settings, save_settings, settings_file  # noqa: E402


class BackendTests(unittest.TestCase):
    def test_commands(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / ('pkgextract.exe' if os.name == 'nt' else 'pkgextract')
            exe.write_bytes(b'mock')
            exe.chmod(0o755)
            p = Path(td) / 'Game With Spaces.pkg'
            dest = Path(td) / 'Destination With Spaces'
            cmd = Extractor('pkgextract', exe).command(p, dest)
            self.assertEqual(cmd, [str(exe), str(p), '-o', str(dest)])
            tool = Extractor('pkgtool', exe).command(p, dest)
            self.assertEqual(tool, [str(exe), 'pkg_extract', str(p), str(dest)])

    def test_dotnet_dll_command(self):
        with tempfile.TemporaryDirectory() as td:
            entry = Path(td) / 'PkgTool.Core.dll'
            entry.write_bytes(b'fixture')
            with patch('pkg_batch_extractor.backend.shutil.which', return_value='/usr/bin/dotnet'):
                command = Extractor('pkgtool', entry).command(Path('a.pkg'), Path('out'))
                self.assertEqual(command, ['dotnet', str(entry), 'pkg_extract', 'a.pkg', 'out'])
            with patch('pkg_batch_extractor.backend.shutil.which', return_value=None):
                with self.assertRaisesRegex(FileNotFoundError, 'dotnet'):
                    Extractor('pkgtool', entry).validate()

    def test_missing_executable_and_unknown_kind(self):
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / 'missing.exe'
            with self.assertRaises(FileNotFoundError):
                Extractor('pkgextract', exe).validate()
            with self.assertRaises(ValueError):
                Extractor('unsupported', exe).validate()

    def test_discovery_next_to_application(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tools_dir = root / 'tools'
            tools_dir.mkdir()
            executable = tools_dir / ('pkgextract.exe' if os.name == 'nt' else 'pkgextract')
            executable.write_bytes(b'dummy')
            with patch('pkg_batch_extractor.backend.application_directory', return_value=root):
                self.assertEqual(discover_executable('pkgextract'), executable)

    def test_discovery_prefers_native_binary(self):
        self.assertEqual(engine_filenames('pkgextract', windows=False), ('pkgextract',))
        self.assertEqual(engine_filenames('pkgextract', windows=True), ('pkgextract.exe',))
        self.assertIn('PkgTool.Core.dll', engine_filenames('pkgtool', windows=False))
        self.assertNotIn('PkgTool.exe', engine_filenames('pkgtool', windows=False))

    def test_macos_frozen_app_engine_directory(self):
        with tempfile.TemporaryDirectory() as td:
            app_exe = Path(td) / 'PKG-Batch-Extractor.app' / 'Contents' / 'MacOS' / 'PKG-Batch-Extractor'
            with patch.object(sys, 'frozen', True, create=True), \
                 patch('pkg_batch_extractor.backend.sys.executable', str(app_exe)), \
                 patch('pkg_batch_extractor.backend.sys.platform', 'darwin'):
                self.assertEqual(application_directory(), Path(td))

    def test_linux_appimage_engine_directory(self):
        with tempfile.TemporaryDirectory() as td:
            appimage = Path(td) / 'PKG-Batch-Extractor.AppImage'
            appimage.write_bytes(b'binary')
            with patch.object(sys, 'frozen', True, create=True), \
                 patch('pkg_batch_extractor.backend.sys.executable', str(Path(td) / 'extracted' / 'app')), \
                 patch('pkg_batch_extractor.backend.sys.platform', 'linux'), \
                 patch.dict('pkg_batch_extractor.backend.os.environ', {'APPIMAGE': str(appimage)}):
                self.assertEqual(application_directory(), Path(td))

    def test_bundled_engine_directory_override_is_discovered(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tools_dir = root / 'embedded' / 'tools'
            tools_dir.mkdir(parents=True)
            engine = tools_dir / ('pkgextract.exe' if os.name == 'nt' else 'pkgextract')
            engine.write_bytes(b'engine')
            engine.chmod(0o755)
            with patch.dict('pkg_batch_extractor.backend.os.environ', {'PKG_BATCH_EXTRACTOR_TOOLS': str(tools_dir)}), \
                 patch('pkg_batch_extractor.backend.application_directory', return_value=root):
                self.assertEqual(discover_executable('pkgextract'), engine.resolve())

    def test_macos_bundled_engine_resource_is_discovered(self):
        with tempfile.TemporaryDirectory() as td:
            app = Path(td) / 'PKG-Batch-Extractor.app'
            executable = app / 'Contents' / 'MacOS' / 'PKG-Batch-Extractor'
            engine = app / 'Contents' / 'Resources' / 'tools' / 'pkgextract'
            engine.parent.mkdir(parents=True)
            engine.write_bytes(b'engine')
            engine.chmod(0o755)
            with patch.object(sys, 'frozen', True, create=True), \
                 patch('pkg_batch_extractor.backend.sys.executable', str(executable)), \
                 patch('pkg_batch_extractor.backend.sys.platform', 'darwin'), \
                 patch('pkg_batch_extractor.backend.engine_filenames', return_value=('pkgextract',)):
                self.assertEqual(discover_executable('pkgextract'), engine.resolve())

    def test_settings_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'settings.json'
            with patch('pkg_batch_extractor.settings.settings_file', return_value=target):
                self.assertEqual(load_settings(), {})
                save_settings('pkgextract', '/tools/pkgextract', '/my/output')
                self.assertEqual(load_settings()['output'], '/my/output')
                self.assertEqual(load_settings()['engine'], 'pkgextract')
                target.write_text('{', encoding='utf-8')
                self.assertEqual(load_settings(), {})

    def test_macos_settings_location(self):
        with tempfile.TemporaryDirectory() as td:
            with patch('pkg_batch_extractor.settings.sys.platform', 'darwin'), \
                 patch('pkg_batch_extractor.settings.Path.home', return_value=Path(td)):
                if os.name != 'nt':
                    self.assertEqual(settings_file(), Path(td) / 'Library' / 'Application Support' / 'PKGBatchExtractor' / 'settings.json')


if __name__ == '__main__':
    unittest.main()
