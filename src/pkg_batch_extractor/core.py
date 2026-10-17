"""Pure path/queue helpers for PS4 PKG extraction."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import struct

INVALID_WINDOWS_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}
DISK_SPACE_MULTIPLIER = 2
DISK_SPACE_BUFFER = 100 * 1024 * 1024
TITLE_ID_PATTERN = re.compile(r'^[A-Z]{4}\d{5}$')


@dataclass(frozen=True)
class Job:
    source: Path
    destination: Path


def estimate_required_disk_bytes(jobs: list[Job]) -> int:
    """Estimate extraction space from PKG input sizes with a safety margin.

    Output sizes vary by package format and compression, so this is a warning
    heuristic rather than a promise about the final extracted size.
    """
    input_bytes = sum(job.source.stat().st_size for job in jobs)
    return input_bytes * DISK_SPACE_MULTIPLIER + DISK_SPACE_BUFFER


def format_bytes(count: int) -> str:
    size = float(count)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024 or unit == 'TB':
            return f'{int(size)} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
        size /= 1024
    raise AssertionError('unreachable')


def clean_name(name: str) -> str:
    """Return a safe, short Windows-compatible directory basename."""
    value = INVALID_WINDOWS_NAME_CHARS.sub('_', name).strip().rstrip('. ')
    value = value[:90].rstrip('. ')
    if not value:
        return 'package'
    if value.split('.', 1)[0].upper() in WINDOWS_RESERVED:
        return f'_{value}'
    return value


def normalized_path(path: Path) -> str:
    """Case-insensitive for predictable Windows-style batch de-duplication."""
    return str(path.expanduser().resolve(strict=False)).casefold()


def collect_pkgs(files: list[Path]) -> list[Path]:
    """Deduplicate valid .pkg files while keeping selection order."""
    result: list[Path] = []
    seen: set[str] = set()
    for path in files:
        p = path.expanduser().resolve(strict=False)
        key = normalized_path(p)
        if p.is_file() and p.suffix.lower() == '.pkg' and key not in seen:
            seen.add(key)
            result.append(p)
    return result


def scan_folder(folder: Path) -> list[Path]:
    """Scan one folder, not subfolders, so selections stay predictable."""
    return collect_pkgs([p for p in folder.iterdir() if p.suffix.lower() == '.pkg'])


def plan_jobs(sources: list[Path], output_dir: Path) -> list[Job]:
    """Create unique targets without deleting or overwriting existing dirs."""
    root = output_dir.expanduser().resolve(strict=False)
    reserved: set[str] = set()
    jobs: list[Job] = []
    for source in collect_pkgs(sources):
        base = clean_name(source.stem)
        idx = 1
        while True:
            folder = base if idx == 1 else f'{base} ({idx})'
            dest = root / folder
            key = normalized_path(dest)
            if key not in reserved and not dest.exists() and not dest.is_symlink():
                reserved.add(key)
                jobs.append(Job(source=source, destination=dest))
                break
            idx += 1
    return jobs


def next_available_target(target: Path) -> Path:
    """Re-check the path immediately before publishing an extracted directory."""
    if not target.exists() and not target.is_symlink():
        return target
    base = clean_name(target.name)
    index = 2
    while True:
        candidate = target.parent / f'{base} ({index})'
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
        index += 1


def read_title_id(param_sfo: Path) -> str | None:
    """Read a valid PS4 TITLE_ID from a bounded PARAM.SFO file."""
    try:
        if param_sfo.stat().st_size > 16 * 1024 * 1024:
            return None
        data = param_sfo.read_bytes()
        if len(data) < 20:
            return None
        magic, _version, key_base, data_base, count = struct.unpack_from('<4sIIII', data)
        if magic != b'\x00PSF' or count > 4096:
            return None
        entries_end = 20 + count * 16
        if entries_end > len(data) or key_base < entries_end or data_base < key_base:
            return None
        for index in range(count):
            offset = 20 + index * 16
            key_offset, _fmt, length, _max_len, data_offset = struct.unpack_from('<HHIII', data, offset)
            key_start = key_base + key_offset
            value_start = data_base + data_offset
            if key_start >= data_base or value_start > len(data) or length > len(data) - value_start:
                continue
            key_end = data.find(b'\0', key_start, data_base)
            if key_end < 0 or data[key_start:key_end] != b'TITLE_ID':
                continue
            value = data[value_start:value_start + length].split(b'\0', 1)[0]
            try:
                title_id = value.decode('ascii').strip().upper()
            except UnicodeDecodeError:
                return None
            return title_id if TITLE_ID_PATTERN.fullmatch(title_id) else None
    except (OSError, ValueError, struct.error):
        return None
    return None


def find_title_id(root: Path) -> str | None:
    """Find PARAM.SFO below extracted content without following symlinks."""
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and entry.name.casefold() == 'param.sfo':
                            title_id = read_title_id(Path(entry.path))
                            if title_id:
                                return title_id
                    except OSError:
                        continue
        except OSError:
            continue
    return None
