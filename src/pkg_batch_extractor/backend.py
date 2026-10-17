"""Adapters for bundled and user-selected extraction engines."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys

ENGINE_LABELS = {
    'pkgextract': 'pkgextract (Rust CLI)',
    'pkgtool': 'LibOrbisPkg PkgTool',
}
ENGINE_FILENAMES = {
    'pkgextract': ('pkgextract.exe', 'pkgextract'),
    'pkgtool': ('PkgTool.Core.exe', 'PkgTool.Core', 'PkgTool.exe', 'PkgTool', 'PkgTool.Core.dll'),
}


def engine_filenames(kind: str, *, windows: bool | None = None) -> tuple[str, ...]:
    if kind not in ENGINE_LABELS:
        raise ValueError(f'Unknown engine: {kind}')
    on_windows = os.name == 'nt' if windows is None else windows
    if on_windows:
        return tuple(name for name in ENGINE_FILENAMES[kind] if name.lower().endswith(('.exe', '.dll')))
    return tuple(name for name in ENGINE_FILENAMES[kind] if not name.lower().endswith('.exe'))


def application_directory() -> Path:
    """Find the user-visible app location, including outside a macOS .app bundle."""
    if getattr(sys, 'frozen', False):
        executable = Path(sys.executable).resolve()
        if sys.platform == 'darwin':
            for parent in executable.parents:
                if parent.suffix.lower() == '.app':
                    return parent.parent
        if sys.platform.startswith('linux'):
            appimage = os.environ.get('APPIMAGE')
            if appimage:
                return Path(appimage).expanduser().resolve().parent
        return executable.parent
    return Path(__file__).resolve().parents[2]


def discover_executable(kind: str) -> Path | None:
    if kind not in ENGINE_LABELS:
        raise ValueError(f'Unknown engine: {kind}')
    candidates: list[Path] = []
    bundled_tools = os.environ.get('PKG_BATCH_EXTRACTOR_TOOLS')
    if bundled_tools:
        candidates.append(Path(bundled_tools).expanduser())
    if getattr(sys, 'frozen', False) and sys.platform == 'darwin':
        for parent in Path(sys.executable).resolve().parents:
            if parent.name == 'Contents':
                candidates.append(parent / 'Resources' / 'tools')
                break
    app_dir = application_directory()
    candidates.extend((app_dir / 'tools', app_dir))
    # Preserve search order while avoiding repeated paths.
    candidates = list(dict.fromkeys(path.resolve(strict=False) for path in candidates))
    names = engine_filenames(kind)
    for folder in candidates:
        for name in names:
            path = folder / name
            if path.is_file():
                return path.resolve()
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    return None


@dataclass(frozen=True)
class Extractor:
    kind: str
    executable: Path

    def validate(self) -> None:
        if self.kind not in ENGINE_LABELS:
            raise ValueError('Choose a supported extraction engine.')
        if not self.executable.is_file():
            raise FileNotFoundError(f'Engine executable not found: {self.executable}')
        if self.executable.suffix.lower() == '.dll':
            if self.kind != 'pkgtool':
                raise ValueError('Only PkgTool supports a .dll runtime entrypoint.')
            if shutil.which('dotnet') is None:
                raise FileNotFoundError('The dotnet runtime is required to run PkgTool.Core.dll.')
        elif os.name != 'nt':
            if self.executable.suffix.lower() == '.exe':
                raise ValueError('Select a Linux/macOS engine binary, not a Windows .exe.')
            if not os.access(self.executable, os.X_OK):
                raise PermissionError(f'Engine is not executable; try chmod +x: {self.executable}')

    def command(self, source: Path, staging: Path) -> list[str]:
        self.validate()
        if self.kind == 'pkgextract':
            return [str(self.executable), str(source), '-o', str(staging)]
        if self.kind == 'pkgtool':
            prefix = ['dotnet', str(self.executable)] if self.executable.suffix.lower() == '.dll' else [str(self.executable)]
            return [*prefix, 'pkg_extract', str(source), str(staging)]
        raise ValueError(f'Unsupported engine: {self.kind}')
