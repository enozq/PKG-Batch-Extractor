"""Real Tk smoke test against a fake CLI. Run with xvfb-run on headless Linux."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from pkg_batch_extractor.ui import App  # noqa: E402
from pkg_batch_extractor.backend import Extractor  # noqa: E402


class FakeUIEngine(Extractor):
    def command(self, source, staging):
        return [sys.executable, str(FAKE_SCRIPT), str(source), '-o', str(staging)]


def finish(root, app):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        root.update()
        if not app.running:
            return
        time.sleep(.03)
    raise AssertionError('GUI extraction was stuck')


with tempfile.TemporaryDirectory() as td:
    work = Path(td)
    FAKE_SCRIPT = work / 'fake_cli.py'
    FAKE_SCRIPT.write_text('''
import pathlib, sys
src=pathlib.Path(sys.argv[1]); target=pathlib.Path(sys.argv[3]);
flag=src.parent/'failed-once.marker'
if src.name=='Fail.pkg' and not flag.exists():
    flag.write_text('first run failed', encoding='utf-8')
    print('synthetic first-run failure', flush=True)
    sys.exit(8)
target.mkdir(parents=True)
(target/'content.bin').write_bytes(src.read_bytes())
print('success', flush=True)
''', encoding='utf-8')
    good = work / 'Good.pkg'; good.write_bytes(b'GOOD')
    bad = work / 'Fail.pkg'; bad.write_bytes(b'BAD')
    log = work / 'run.log'
    with patch('pkg_batch_extractor.ui.Extractor', FakeUIEngine), \
         patch('pkg_batch_extractor.ui.save_settings', return_value=None), \
         patch('pkg_batch_extractor.ui.load_settings', return_value={}), \
         patch('pkg_batch_extractor.ui.messagebox.showinfo') as completion_notice:
        root = tk.Tk()
        app = App(root)
        root.update()
        assert app._window_icon is not None
        assert int(app.logs.cget('height')) >= 8
        # The deliberately removed subtitle must not appear in the real Tk tree.
        def texts(widget):
            result = []
            try:
                result.append(widget.cget('text'))
            except tk.TclError:
                pass
            for child in widget.winfo_children():
                result.extend(texts(child))
            return result
        assert not any('A simple, safer batch extraction workspace' in str(x) for x in texts(root))
        app.output_var.set(str(work / 'outputs'))
        app.exe_var.set(sys.executable)
        app._append_sources([good, bad])
        assert len(app.current_jobs) == 2
        app._start()
        finish(root, app)
        assert (work / 'outputs' / 'Good' / 'content.bin').read_bytes() == b'GOOD'
        assert len(app.failed_sources) == 1, app.failed_sources
        assert int(float(app.progress_bar['value'])) == 2  # All jobs were processed.
        assert str(app.retry_button['state']) == 'normal'
        app._retry_failed()
        finish(root, app)
        assert (work / 'outputs' / 'Fail' / 'content.bin').read_bytes() == b'BAD'
        assert not app.failed_sources
        assert int(float(app.progress_bar['value'])) == 1
        assert 'Fail.pkg: 1 files' in app.activity_var.get()
        assert completion_notice.call_count == 1
        with patch('pkg_batch_extractor.ui.filedialog.asksaveasfilename', return_value=str(log)):
            app._export_log()
        assert 'synthetic first-run failure' in log.read_text(encoding='utf-8')
        assert 'success' in log.read_text(encoding='utf-8')
        assert 'Extraction finished successfully.' in log.read_text(encoding='utf-8')
        assert 'Final snapshot:' not in log.read_text(encoding='utf-8')
        app._clear()
        assert app.sources == [] and app.failed_sources == []
        assert str(app.retry_button['state']) == 'disabled'
        app._on_close()
print('GUI SMOKE PASS: load, select, first failure, retry, success, save log')
