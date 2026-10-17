"""Create a README screenshot of synthetic queue entries on Linux with Tk."""
from pathlib import Path
import sys
import tempfile
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pkg_batch_extractor.ui import App  # noqa: E402

try:
    from PIL import ImageGrab
except ImportError as exc:
    raise SystemExit('Pillow is required only to take the screenshot.') from exc

with tempfile.TemporaryDirectory() as td:
    work = Path(td)
    names = [('Game_Demo.pkg', 64 * 1024 ** 2), ('AddOn_Content.pkg', 8 * 1024 ** 2),
             ('Game_Second.pkg', 20 * 1024 ** 2)]
    pkg_files = []
    for name, size in names:
        path = work / name
        with path.open('wb') as f:
            f.truncate(size)  # Sparse synthetic files, not PS4 content.
        pkg_files.append(path)
    root = tk.Tk()
    app = App(root)
    app.output_var.set(str(Path.home() / 'Extracted-PKG'))
    app.exe_var.set('')
    app._append_sources(pkg_files)
    root.update_idletasks()
    root.update()
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    image = ImageGrab.grab(bbox=(x, y, x+w, y+h))
    image.save(ROOT / 'docs' / 'screenshot.png')
    root.destroy()
    print(f'Captured synthetic Linux UI screenshot: {w}x{h}')
