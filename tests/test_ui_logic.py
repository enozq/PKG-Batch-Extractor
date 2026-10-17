"""Headless regressions for GUI event processing and state transitions."""
from pathlib import Path
from collections import deque
import queue
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from pkg_batch_extractor.ui import App, MAX_UI_EVENTS_PER_TICK  # noqa: E402


class FakeRoot:
    def __init__(self):
        self.pending = []
        self.cancelled = []

    def after(self, delay, callback):
        self.pending.append((delay, callback))
        return f'id-{len(self.pending)}'

    def after_cancel(self, handle):
        self.cancelled.append(handle)


class UILogicTests(unittest.TestCase):
    def make_app(self):
        app = App.__new__(App)
        app.root = FakeRoot()
        app.running = False
        app._pending_preview_refresh = None
        app._refresh_table = Mock()
        app._sync_retry_button = Mock()
        app.status_var = Mock()
        app.activity_var = Mock()
        return app

    def test_package_progress_advances_left_to_right_by_completed_packages(self):
        app = self.make_app()
        app.progress_bar = Mock()
        app.events = queue.Queue()
        app.running = True
        app.current_jobs = [object(), object(), object()]
        app.progress_var = Mock()
        app.events.put(('progress', 1, 3, 1, 0))
        app._pump_events()
        app.progress_bar.configure.assert_called_once_with(value=1)
        app.progress_var.set.assert_called_once_with('1 completed / 3  •  0 failed')

    def test_progress_bar_is_determinate_and_starts_at_zero(self):
        app = self.make_app()
        app.progress_bar = Mock()
        app._configure_batch_progress(4)
        app.progress_bar.configure.assert_called_once_with(
            mode='determinate', maximum=4, value=0)

    def test_output_path_refresh_is_debounced(self):
        app = self.make_app()
        for _ in range(100):
            app._schedule_preview_refresh()
        self.assertEqual(app._refresh_table.call_count, 0)
        self.assertEqual(len(app.root.cancelled), 99)
        self.assertEqual(len(app.root.pending), 100)
        self.assertEqual(app.root.pending[-1][0], 200)
        app._finish_preview_refresh()
        app._refresh_table.assert_called_once()
        self.assertIsNone(app._pending_preview_refresh)

    def test_no_preview_refresh_while_running(self):
        app = self.make_app()
        app._schedule_preview_refresh()
        app.running = True
        app._schedule_preview_refresh()
        self.assertEqual(len(app.root.cancelled), 1)
        self.assertIsNone(app._pending_preview_refresh)
        app._finish_preview_refresh()
        app._refresh_table.assert_not_called()

    def test_large_log_batch_does_not_starve_ui(self):
        app = self.make_app()
        app.events = queue.Queue()
        app._write_log = Mock()
        for i in range(500):
            app.events.put(('log', str(i)))
        app._pump_events()
        self.assertEqual(app._write_log.call_count, MAX_UI_EVENTS_PER_TICK)
        self.assertEqual(app.events.qsize(), 500 - MAX_UI_EVENTS_PER_TICK)
        self.assertEqual(app.root.pending[-1][0], 1)
        while not app.events.empty():
            app._pump_events()
        self.assertEqual(app._write_log.call_count, 500)
        self.assertEqual(app.root.pending[-1][0], 120)

    def test_live_metrics_update_extraction_activity(self):
        app = self.make_app()
        app.events = queue.Queue()
        app.events.put(('metrics', 'Game.pkg', 17, 4096, 8, 2 * 1024 * 1024))
        app._pump_events()
        app.activity_var.set.assert_called_once_with('Game.pkg: 17 files • 4.0 KB extracted • 2.00 MB/s • 00:08 elapsed')
        app.status_var.set.assert_called_once_with('Extracting Game.pkg — 17 files, 4.0 KB')

    def test_live_metrics_without_reliable_speed_do_not_show_a_rate(self):
        app = self.make_app()
        app.events = queue.Queue()
        app.events.put(('metrics', 'Game.pkg', 17, 4096, 8, None))
        app._pump_events()
        self.assertEqual(app.activity_var.set.call_args.args[0],
                         'Game.pkg: 17 files • 4.0 KB extracted • 00:08 elapsed')

    def test_log_writes_scroll_to_bottom(self):
        app = self.make_app()
        app.log_history = deque(maxlen=10000)
        app._visible_log_lines = 0
        app.logs = Mock()
        app._write_log('new extraction record')
        app.logs.see.assert_called_once_with('end')
        app.logs.yview_moveto.assert_called_once_with(1.0)

    def test_success_notification_shown_only_for_clean_completion(self):
        app = self.make_app()
        app.output_var = Mock()
        app.output_var.get.return_value = 'C:/Extracted'
        with patch('pkg_batch_extractor.ui.messagebox.showinfo') as showinfo:
            app._notify_success(2, 0, False)
            showinfo.assert_called_once()
            self.assertEqual(showinfo.call_args.args[0], 'Extraction complete')
            showinfo.reset_mock()
            app._notify_success(1, 1, False)
            app._notify_success(1, 0, True)
            showinfo.assert_not_called()

    def test_successful_finish_keeps_clear_result_messages_in_log(self):
        app = self.make_app()
        app.events = queue.Queue()
        app.events.put(('finished', 1, 0, False))
        app.running = True
        app.current_jobs = [object()]
        app.progress_bar = Mock()
        app._set_controls = Mock()
        app._write_log = Mock()
        app._close_after_run = False
        app._notify_success = Mock()
        app._pump_events()
        self.assertEqual([call.args[0] for call in app._write_log.call_args_list], [
            'Extraction finished successfully.',
            'Finished: 1 completed, 0 failed.',
        ])

    def test_low_space_warning_uses_free_bytes_and_estimate(self):
        app = self.make_app()
        app._write_log = Mock()
        jobs = [SimpleNamespace(source=Path('game.pkg'))]
        with patch('pkg_batch_extractor.ui.estimate_required_disk_bytes', return_value=1000), \
             patch('pkg_batch_extractor.ui.shutil.disk_usage', return_value=SimpleNamespace(free=500)), \
             patch('pkg_batch_extractor.ui.messagebox.showwarning') as warning:
            app._warn_if_low_disk_space(Path('out'), jobs)
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[0], 'Low disk space')
        app._write_log.assert_called_once()

    def test_close_while_running_asks_and_cancels_only_after_yes(self):
        app = self.make_app()
        app.running = True
        app._close_after_run = False
        app.runner = Mock()
        app.cancel_button = Mock()
        with patch('pkg_batch_extractor.ui.messagebox.askyesno', return_value=False):
            app._on_close()
        app.runner.cancel.assert_not_called()
        self.assertFalse(app._close_after_run)
        with patch('pkg_batch_extractor.ui.messagebox.askyesno', return_value=True):
            app._on_close()
        app.runner.cancel.assert_called_once()
        self.assertTrue(app._close_after_run)

    def test_confirmed_exit_closes_after_runner_finished_event(self):
        app = self.make_app()
        app.events = queue.Queue()
        app.events.put(('finished', 0, 0, True))
        app.running = True
        app._close_after_run = True
        app.current_jobs = []
        app.progress_bar = Mock()
        app._set_controls = Mock()
        app._write_log = Mock()
        app._save_and_close = Mock()
        app._pump_events()
        self.assertFalse(app.running)
        app.progress_bar.stop.assert_called_once()
        app._save_and_close.assert_called_once()
        self.assertEqual(app.root.pending, [])

    def test_clear_resets_retry_state(self):
        app = self.make_app()
        app.sources = [Path('Game.pkg')]
        app.failed_sources = [Path('Game.pkg')]
        app._clear()
        self.assertEqual(app.sources, [])
        self.assertEqual(app.failed_sources, [])
        app._sync_retry_button.assert_called_once()

    def test_remove_cleans_only_removed_failure(self):
        app = self.make_app()
        app.sources = [Path('Bad.pkg'), Path('Other.pkg'), Path('Good.pkg')]
        app.failed_sources = [Path('Bad.pkg'), Path('Other.pkg')]
        app.table = Mock()
        app.table.selection.return_value = ('0', '2')
        app._remove()
        self.assertEqual(app.sources, [Path('Other.pkg')])
        self.assertEqual(app.failed_sources, [Path('Other.pkg')])
        app._sync_retry_button.assert_called_once()

    def test_shortcut_ignored_during_run(self):
        app = self.make_app()
        app._add_dialog = Mock()
        app._add_folder = Mock()
        app.running = True
        self.assertEqual(app._shortcut_add(None), 'break')
        self.assertEqual(app._shortcut_add_folder(None), 'break')
        app._add_dialog.assert_not_called()
        app._add_folder.assert_not_called()
        app.running = False
        app._shortcut_add(None)
        app._shortcut_add_folder(None)
        app._add_dialog.assert_called_once()
        app._add_folder.assert_called_once()


if __name__ == '__main__':
    unittest.main()
