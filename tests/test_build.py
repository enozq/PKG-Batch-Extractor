import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_pkg', root / 'build.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BuildCommandTests(unittest.TestCase):
    def test_windows_build_uses_clean_staging_and_remaps_user_path(self):
        script = (root / 'build_windows.bat').read_text(encoding='utf-8')
        self.assertIn('--remap-path-prefix=%USERPROFILE%=<USER>', script)
        self.assertIn('set "PKG_BATCH_EXTRACTOR_DIST_DIR=%PKG_WINDOWS_DIST%"', script)
        self.assertIn("Compress-Archive -Force -Path '%PKG_WINDOWS_DIST%\\*'", script)
        self.assertIn('Unexpected non-Windows PKG engine', script)
        self.assertNotIn("-Path 'dist/PKG-Batch-Extractor.exe','dist/tools'", script)

    def test_appimage_packaging_uses_pinned_runtime_and_root_icon(self):
        packaging = (root / 'package_linux_appimage.sh').read_text(encoding='utf-8')
        self.assertIn('--runtime-file "$APPIMAGETOOL_RUNTIME_FILE"', packaging)
        self.assertIn('pkgextract-RUST-THIRD-PARTY.md', packaging)
        self.assertIn('licenses/.', packaging)
        self.assertIn('"$ROOT/assets/app-icon.png" "$APPDIR/pkg-batch-extractor.png"', packaging)
        self.assertIn('mv -f "$BUILD_IMAGE" "$ROOT/dist/PKG-Batch-Extractor-x86_64.AppImage"', packaging)

    def test_windows(self):
        command = module.command_for_platform('win32')
        self.assertIn('--onefile', command)
        self.assertIn('--windowed', command)
        self.assertIn('--collect-all', command)
        self.assertIn(str(root / 'assets' / 'app-icon.ico'), command)
        self.assertIn('--add-data', command)

    def test_linux(self):
        command = module.command_for_platform('linux')
        self.assertIn('--onefile', command)

    def test_macos(self):
        command = module.command_for_platform('darwin')
        self.assertIn('--onedir', command)
        self.assertNotIn('--onefile', command)
        self.assertIn(str(root / 'assets' / 'app-icon.icns'), command)
        self.assertIn('--add-data', command)

    def test_icon_assets_exist_for_build_targets(self):
        for filename in ('app-icon.png', 'app-icon.ico', 'app-icon.icns'):
            self.assertTrue((root / 'assets' / filename).is_file(), filename)

    def test_runtime_component_license_notices_are_present(self):
        for filename in ('tkinterdnd2-MIT.txt', 'TkDND-license.terms', 'Tcl-license.terms', 'Tk-license.terms'):
            self.assertTrue((root / 'licenses' / filename).is_file(), filename)
        self.assertIsNotNone(module.python_license_path(),
                        'build interpreter license text is required')
        self.assertIsNotNone(module.pyinstaller_license_path(),
                        'PyInstaller COPYING.txt is required')

    def test_macos_dmg_command_packages_app_bundle(self):
        app = root / 'dist' / 'PKG-Batch-Extractor.app'
        command = module.macos_dmg_command(app)
        self.assertEqual(command[0:6], ['hdiutil', 'create', '-volname', module.APP_NAME,
                                       '-srcfolder', str(app)])
        self.assertEqual(command[-2:], ['UDZO', str(root / 'dist' / 'PKG-Batch-Extractor.dmg')])

    def test_engine_is_copied_to_portable_platform_locations(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            engine = temp / 'pkgextract'
            engine.write_bytes(b'engine')
            engine_license = temp / 'upstream-license'
            engine_license.write_text('Unlicense text', encoding='utf-8')
            engine_lock = temp / 'Cargo.lock'
            engine_lock.write_text('lock data', encoding='utf-8')
            rust_notices = temp / 'rust-notices.md'
            rust_notices.write_text('Rust license notices', encoding='utf-8')
            dist = temp / 'dist'
            app = dist / 'PKG-Batch-Extractor.exe'
            app.parent.mkdir()
            app.write_bytes(b'app')
            with patch.dict(os.environ, {
                'PKG_BATCH_EXTRACTOR_ENGINE_LICENSE': str(engine_license),
                'PKG_BATCH_EXTRACTOR_ENGINE_LOCK': str(engine_lock),
                'PKG_BATCH_EXTRACTOR_RUST_NOTICES': str(rust_notices),
            }):
                destination = module.include_engine(engine, 'win32', app, dist)
            self.assertEqual(destination, dist / 'tools' / 'pkgextract.exe')
            self.assertEqual(destination.read_bytes(), b'engine')
            self.assertTrue((dist / 'THIRD_PARTY.md').is_file())
            self.assertEqual((dist / 'pkgextract-LICENSE.txt').read_text(encoding='utf-8'), 'Unlicense text')
            self.assertEqual((dist / 'pkgextract-Cargo.lock').read_text(encoding='utf-8'), 'lock data')
            self.assertEqual((dist / 'pkgextract-RUST-THIRD-PARTY.md').read_text(encoding='utf-8'), 'Rust license notices')
            self.assertTrue((dist / 'licenses' / 'tkinterdnd2-MIT.txt').is_file())
            self.assertTrue((dist / 'licenses' / 'TkDND-license.terms').is_file())
            self.assertTrue((dist / 'licenses' / 'Tcl-license.terms').is_file())
            self.assertTrue((dist / 'licenses' / 'Tk-license.terms').is_file())
            self.assertTrue((dist / 'licenses' / 'Python-LICENSE.txt').is_file())
            self.assertTrue((dist / 'licenses' / 'PyInstaller-COPYING.txt').is_file())

            mac_app = temp / 'PKG-Batch-Extractor.app'
            (mac_app / 'Contents' / 'Resources').mkdir(parents=True)
            with patch.dict(os.environ, {
                'PKG_BATCH_EXTRACTOR_ENGINE_LICENSE': str(engine_license),
                'PKG_BATCH_EXTRACTOR_ENGINE_LOCK': str(engine_lock),
                'PKG_BATCH_EXTRACTOR_RUST_NOTICES': str(rust_notices),
            }):
                destination = module.include_engine(engine, 'darwin', mac_app, dist)
            self.assertEqual(destination, mac_app / 'Contents' / 'Resources' / 'tools' / 'pkgextract')
            self.assertTrue((mac_app / 'Contents' / 'Resources' / 'THIRD_PARTY.md').is_file())
            self.assertTrue((mac_app / 'Contents' / 'Resources' / 'pkgextract-LICENSE.txt').is_file())
            self.assertTrue((mac_app / 'Contents' / 'Resources' / 'licenses' / 'TkDND-license.terms').is_file())
            self.assertTrue((mac_app / 'Contents' / 'Resources' / 'licenses' / 'Python-LICENSE.txt').is_file())
            self.assertTrue((mac_app / 'Contents' / 'Resources' / 'licenses' / 'PyInstaller-COPYING.txt').is_file())
            self.assertTrue((mac_app / 'Contents' / 'Resources' / 'pkgextract-RUST-THIRD-PARTY.md').is_file())

    def test_engine_already_at_destination_is_not_copied_onto_itself(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            dist = temp / 'dist'
            engine = dist / 'tools' / 'pkgextract.exe'
            engine.parent.mkdir(parents=True)
            engine.write_bytes(b'engine')
            license_file = dist / 'pkgextract-LICENSE.txt'; license_file.write_text('license', encoding='utf-8')
            lock_file = dist / 'pkgextract-Cargo.lock'; lock_file.write_text('lock', encoding='utf-8')
            notices_file = dist / 'pkgextract-RUST-THIRD-PARTY.md'; notices_file.write_text('notices', encoding='utf-8')
            with patch.dict(os.environ, {
                'PKG_BATCH_EXTRACTOR_ENGINE_LICENSE': str(license_file),
                'PKG_BATCH_EXTRACTOR_ENGINE_LOCK': str(lock_file),
                'PKG_BATCH_EXTRACTOR_RUST_NOTICES': str(notices_file),
            }):
                result = module.include_engine(engine, 'win32', dist / 'app.exe', dist)
            self.assertEqual(result, engine)
            self.assertEqual(engine.read_bytes(), b'engine')

    def test_unknown_platform(self):
        with self.assertRaises(RuntimeError):
            module.command_for_platform('plan9')

    def test_build_can_target_a_fresh_output_directory(self):
        with tempfile.TemporaryDirectory() as td:
            temp = Path(td)
            engine = temp / 'pkgextract.exe'; engine.write_bytes(b'engine')
            license_file = temp / 'LICENSE'; license_file.write_text('license', encoding='utf-8')
            lock_file = temp / 'Cargo.lock'; lock_file.write_text('lock', encoding='utf-8')
            notices_file = temp / 'rust-notices.md'; notices_file.write_text('notices', encoding='utf-8')
            output = temp / 'release-output'
            with patch.dict(os.environ, {
                'PKG_BATCH_EXTRACTOR_ENGINE': str(engine),
                'PKG_BATCH_EXTRACTOR_ENGINE_LICENSE': str(license_file),
                'PKG_BATCH_EXTRACTOR_ENGINE_LOCK': str(lock_file),
                'PKG_BATCH_EXTRACTOR_RUST_NOTICES': str(notices_file),
                'PKG_BATCH_EXTRACTOR_DIST_DIR': str(output),
            }), patch.object(module.sys, 'platform', 'win32'):
                def build(command, **_kwargs):
                    self.assertEqual(command[command.index('--distpath') + 1], str(output))
                    (output / f'{module.APP_NAME}.exe').write_bytes(b'app')
                with patch.object(module.subprocess, 'run', side_effect=build):
                    module.main()
            self.assertEqual((output / f'{module.APP_NAME}.exe').read_bytes(), b'app')
            self.assertEqual((output / 'tools' / 'pkgextract.exe').read_bytes(), b'engine')


if __name__ == '__main__':
    unittest.main()
