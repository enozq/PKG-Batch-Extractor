"""Small settings file; no input PKG history or passcodes are stored."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def settings_file() -> Path:
    if os.name == 'nt':
        base = Path(os.environ.get('APPDATA') or Path.home())
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'PKGBatchExtractor' / 'settings.json'


def load_settings() -> dict[str, str]:
    try:
        data = json.loads(settings_file().read_text(encoding='utf-8'))
        return {k: v for k, v in data.items() if k in {'engine', 'executable', 'output'} and isinstance(v, str)}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def save_settings(engine: str, executable: str, output: str) -> None:
    target = settings_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps({'engine': engine, 'executable': executable, 'output': output}, indent=2), encoding='utf-8')
    tmp.replace(target)
