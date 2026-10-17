"""Build the desktop app on the *host* OS (not cross-compilation)."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import os
import shutil
import sysconfig
from importlib import metadata

ROOT = Path(__file__).resolve().parent
APP_NAME = 'PKG-Batch-Extractor'


def copy_if_different(source: Path, destination: Path) -> None:
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def python_license_path() -> Path | None:
    candidates = (
        Path(sys.base_prefix) / 'LICENSE.txt',
        Path(sys.base_prefix) / 'LICENSE',
        Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt',
        Path(sysconfig.get_path('stdlib')) / 'LICENSE',
    )
    return next((path for path in candidates if path.is_file()), None)


def pyinstaller_license_path() -> Path | None:
    distribution = metadata.distribution('PyInstaller')
    return next((
        Path(distribution.locate_file(file))
        for file in distribution.files or ()
        if str(file).lower().endswith('/licenses/copying.txt')
    ), None)


def command_for_platform(platform: str) -> list[str]:
    if platform.startswith('win'):
        kind = '--onefile'
    elif platform.startswith('linux'):
        kind = '--onefile'
    elif platform == 'darwin':
        # PyInstaller recommends onedir .app bundles for macOS rather than onefile.
        kind = '--onedir'
    else:
        raise RuntimeError(f'Unsupported build platform: {platform}')
    icon = ROOT / 'assets' / ('app-icon.ico' if platform.startswith('win') else 'app-icon.icns')
    command = [
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        kind, '--windowed', '--name', APP_NAME, '--paths', str(ROOT / 'src'),
        '--collect-all', 'tkinterdnd2', '--add-data',
        f"{ROOT / 'assets' / 'app-icon.png'}{os.pathsep}assets",
        str(ROOT / 'run.py'),
    ]
    if platform.startswith('win') or platform == 'darwin':
        command[-1:-1] = ['--icon', str(icon)]
    return command


def macos_dmg_command(app_path: Path) -> list[str]:
    """Create a compressed disk image containing the app bundle."""
    return [
        'hdiutil', 'create', '-volname', APP_NAME, '-srcfolder', str(app_path),
        '-ov', '-format', 'UDZO', str(app_path.parent / f'{APP_NAME}.dmg'),
    ]


def include_engine(engine: Path, platform: str, app_path: Path, dist_dir: Path) -> Path:
    """Copy the bundled pkgextract into the platform's adjacent or app resource path."""
    if not engine.is_file():
        raise FileNotFoundError(f'PKG extractor binary not found: {engine}')
    if platform == 'darwin':
        tools_dir = app_path / 'Contents' / 'Resources' / 'tools'
    else:
        tools_dir = dist_dir / 'tools'
    tools_dir.mkdir(parents=True, exist_ok=True)
    filename = 'pkgextract.exe' if platform.startswith('win') else 'pkgextract'
    destination = tools_dir / filename
    copy_if_different(engine, destination)
    if platform != 'win32':
        destination.chmod(destination.stat().st_mode | 0o111)
    notice = ROOT / 'THIRD_PARTY.md'
    if platform == 'darwin':
        shutil.copy2(notice, app_path / 'Contents' / 'Resources' / 'THIRD_PARTY.md')
    else:
        shutil.copy2(notice, dist_dir / 'THIRD_PARTY.md')
    license_root = app_path / 'Contents' / 'Resources' if platform == 'darwin' else dist_dir
    shutil.copy2(ROOT / 'LICENSE', license_root / 'LICENSE')
    bundled_licenses = license_root / 'licenses'
    bundled_licenses.mkdir(parents=True, exist_ok=True)
    for filename in ('tkinterdnd2-MIT.txt', 'TkDND-license.terms', 'Tcl-license.terms', 'Tk-license.terms'):
        copy_if_different(ROOT / 'licenses' / filename, bundled_licenses / filename)
    python_license = python_license_path()
    if python_license is None:
        raise FileNotFoundError(f'Python license text was not found under {sys.base_prefix}')
    copy_if_different(python_license, bundled_licenses / 'Python-LICENSE.txt')
    pyinstaller_license = pyinstaller_license_path()
    if pyinstaller_license is None:
        raise FileNotFoundError('PyInstaller COPYING.txt was not found in the build environment')
    copy_if_different(pyinstaller_license, bundled_licenses / 'PyInstaller-COPYING.txt')
    engine_license = os.environ.get('PKG_BATCH_EXTRACTOR_ENGINE_LICENSE')
    if engine_license:
        copy_if_different(Path(engine_license), license_root / 'pkgextract-LICENSE.txt')
    engine_lock = os.environ.get('PKG_BATCH_EXTRACTOR_ENGINE_LOCK')
    if engine_lock:
        copy_if_different(Path(engine_lock), license_root / 'pkgextract-Cargo.lock')
    rust_notices = os.environ.get('PKG_BATCH_EXTRACTOR_RUST_NOTICES')
    if rust_notices:
        copy_if_different(Path(rust_notices), license_root / 'pkgextract-RUST-THIRD-PARTY.md')
    return destination


def main() -> None:
    engine_value = os.environ.get('PKG_BATCH_EXTRACTOR_ENGINE', '').strip()
    if not engine_value:
        raise RuntimeError('Set PKG_BATCH_EXTRACTOR_ENGINE and build from the supported pkgextract source tag.')
    if not all(os.environ.get(key) for key in (
        'PKG_BATCH_EXTRACTOR_ENGINE_LICENSE',
        'PKG_BATCH_EXTRACTOR_ENGINE_LOCK',
        'PKG_BATCH_EXTRACTOR_RUST_NOTICES',
    )):
        raise RuntimeError('Set the pkgextract source license, Cargo.lock, and generated Rust dependency notices before building a distributable package.')
    engine = Path(engine_value).expanduser().resolve()
    output_dir = Path(os.environ.get('PKG_BATCH_EXTRACTOR_DIST_DIR', ROOT / 'dist')).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    command = command_for_platform(sys.platform) + ['--distpath', str(output_dir)]
    subprocess.run(command, check=True, cwd=ROOT)
    if sys.platform == 'darwin':
        location = output_dir / f'{APP_NAME}.app'
    elif sys.platform == 'win32':
        location = output_dir / f'{APP_NAME}.exe'
    else:
        location = output_dir / APP_NAME
    bundled_engine = include_engine(
        engine, sys.platform,
        location if sys.platform == 'darwin' else output_dir / f'{APP_NAME}.app',
        output_dir,
    )
    print(f'Bundled PKG engine: {bundled_engine}')
    print(f'Built: {location}')
    if sys.platform == 'darwin':
        image = location.parent / f'{APP_NAME}.dmg'
        subprocess.run(macos_dmg_command(location), check=True, cwd=ROOT)
        print(f'Built: {image}')


if __name__ == '__main__':
    main()
