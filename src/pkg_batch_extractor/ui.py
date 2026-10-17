"""Tk/ttk desktop UI. TkinterDnD2 adds optional native drag-and-drop."""
from __future__ import annotations

import os
from pathlib import Path
import queue
from collections import deque
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Iterable

from . import __version__
from .backend import ENGINE_LABELS, Extractor, discover_executable
from .core import collect_pkgs, estimate_required_disk_bytes, format_bytes, plan_jobs, scan_folder
from .runner import JobRunner
from .settings import load_settings, save_settings

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore[import-not-found]
except ImportError:  # Drag & drop is optional; file/folder picker always works.
    DND_FILES = None
    TkinterDnD = None

BG = '#0d1320'
PANEL = '#182233'
PANEL_2 = '#202d40'
INK = '#f2f6fd'
MUTED = '#a7b5cb'
ACCENT = '#62b6ff'
SUCCESS = '#79d7a1'
ERROR = '#ff939a'
FONT = 'Segoe UI' if os.name == 'nt' else ('Helvetica Neue' if sys.platform == 'darwin' else 'DejaVu Sans')
MAX_UI_EVENTS_PER_TICK = 150  # A chatty engine must not freeze the Tk event loop.
MAX_VISIBLE_LOG_LINES = 300


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f'PKG Batch Extractor — v{__version__}')
        self.root.geometry('1080x900')
        self.root.minsize(870, 780)
        self.root.configure(background=BG)
        self._window_icon: tk.PhotoImage | None = None
        self._header_icon: tk.PhotoImage | None = None
        self._configure_icon()
        self.sources: list[Path] = []
        self.events: queue.Queue[tuple] = queue.Queue()
        self.runner = JobRunner(self.events)
        self.running = False
        self.rows: list[str] = []
        self.current_jobs = []
        self.failed_sources: list[Path] = []
        self.log_history: deque[str] = deque(maxlen=10000)
        self._visible_log_lines = 0
        self._pending_preview_refresh: str | None = None
        self._close_after_run = False
        self.loaded = load_settings()
        self._pending_drop_error = False

        engine_name = self.loaded.get('engine', 'pkgextract')
        if engine_name not in ENGINE_LABELS:
            engine_name = 'pkgextract'
        self.engine_var = tk.StringVar(value=ENGINE_LABELS[engine_name])
        executable = self.loaded.get('executable') or str(discover_executable(engine_name) or '')
        self.exe_var = tk.StringVar(value=executable)
        self.output_var = tk.StringVar(value=self.loaded.get('output') or str(Path.home() / 'Extracted-PKG'))
        self.summary_var = tk.StringVar(value='No packages selected')
        self.status_var = tk.StringVar(value='Ready — choose PKG files to begin.')
        self.progress_var = tk.StringVar(value='0 / 0 completed')
        self.activity_var = tk.StringVar(value='Waiting for extraction activity.')

        self._setup_style()
        self._build()
        self.output_var.trace_add('write', self._schedule_preview_refresh)
        self.root.bind('<Control-o>', self._shortcut_add)
        self.root.bind('<Command-o>', self._shortcut_add)
        self.root.bind('<Control-Shift-O>', self._shortcut_add_folder)
        self.root.bind('<Command-Shift-O>', self._shortcut_add_folder)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.root.after(100, self._pump_events)

    def _setup_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('App.TFrame', background=BG)
        style.configure('Card.TFrame', background=PANEL)
        style.configure('Card.TLabel', background=PANEL, foreground=INK, font=(FONT, 11))
        style.configure('Muted.TLabel', background=PANEL, foreground=MUTED, font=(FONT, 10))
        style.configure('Title.TLabel', background=BG, foreground=INK, font=(FONT, 25, 'bold'))
        style.configure('Version.TLabel', background=BG, foreground=MUTED, font=(FONT, 10))
        style.configure('Heading.TLabel', background=PANEL, foreground=INK, font=(FONT, 13, 'bold'))
        style.configure('Primary.TButton', background=ACCENT, foreground='#0b1928',
                        font=(FONT, 10, 'bold'), borderwidth=0, padding=(19, 11))
        style.map('Primary.TButton', background=[('active', '#91ceff'), ('disabled', '#3a5369')],
                  foreground=[('disabled', '#b0b9c4')])
        style.configure('Secondary.TButton', background=PANEL_2, foreground=INK,
                        borderwidth=0, padding=(13, 8), font=(FONT, 10))
        style.map('Secondary.TButton', background=[('active', '#30425c'), ('disabled', '#263142')],
                  foreground=[('disabled', '#718198')])
        style.configure('Danger.TButton', background='#563842', foreground='#ffe6e9',
                        borderwidth=0, padding=(13, 8), font=(FONT, 10))
        style.map('Danger.TButton', background=[('active', '#794550'), ('disabled', '#263142')])
        style.configure('App.TEntry', fieldbackground=PANEL_2, foreground=INK,
                        insertcolor=INK, borderwidth=0, padding=8)
        style.configure('App.TCombobox', fieldbackground=PANEL_2, background=PANEL_2,
                        foreground=INK, arrowcolor=INK, borderwidth=0, padding=7)
        style.map('App.TCombobox', fieldbackground=[('readonly', PANEL_2)],
                  foreground=[('readonly', INK)])
        style.configure('Pkg.Treeview', background=PANEL_2, fieldbackground=PANEL_2,
                        foreground=INK, rowheight=33, borderwidth=0, font=(FONT, 10))
        style.configure('Pkg.Treeview.Heading', background=PANEL, foreground=MUTED,
                        relief='flat', padding=11, font=(FONT, 10, 'bold'))
        style.map('Pkg.Treeview', background=[('selected', '#325a82')], foreground=[('selected', '#ffffff')])
        style.map('Pkg.Treeview.Heading', background=[('active', PANEL)])
        style.configure('Accent.Horizontal.TProgressbar', troughcolor=PANEL_2,
                        background=ACCENT, borderwidth=0, thickness=11)

    def _configure_icon(self) -> None:
        bases = [Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))]
        if getattr(sys, 'frozen', False):
            executable = Path(sys.executable).resolve()
            bases.append(executable.parent)
            if sys.platform == 'darwin':
                for parent in executable.parents:
                    if parent.name == 'Contents':
                        bases.append(parent / 'Resources')
                        break
        png_icon = next((base / 'assets' / 'app-icon.png' for base in bases
                         if (base / 'assets' / 'app-icon.png').is_file()), None)
        ico_icon = next((base / 'assets' / 'app-icon.ico' for base in bases
                         if (base / 'assets' / 'app-icon.ico').is_file()), None)
        try:
            if png_icon is None:
                return
            self._window_icon = tk.PhotoImage(file=str(png_icon))
            self.root.iconphoto(True, self._window_icon)
            self._header_icon = self._window_icon.subsample(10, 10)
            if os.name == 'nt' and ico_icon is not None:
                self.root.iconbitmap(default=str(ico_icon))
        except tk.TclError:
            # Window icon assets are optional for source runs from partial checkouts.
            self._window_icon = None

    def _build(self) -> None:
        shell = ttk.Frame(self.root, style='App.TFrame', padding=20)
        shell.pack(fill='both', expand=True)

        header = ttk.Frame(shell, style='App.TFrame')
        header.pack(fill='x', pady=(0, 15))
        left = ttk.Frame(header, style='App.TFrame')
        left.pack(side='left', fill='x', expand=True)
        if self._header_icon is not None:
            ttk.Label(left, image=self._header_icon).pack(side='left', padx=(0, 12))
        ttk.Label(left, text='PKG Batch Extractor', style='Title.TLabel').pack(side='left', anchor='center')
        ttk.Label(header, text=f'VERSION {__version__}', style='Version.TLabel').pack(side='right', anchor='n')

        card = ttk.Frame(shell, style='Card.TFrame', padding=14)
        card.pack(fill='both', expand=True, pady=(0, 10))
        row = ttk.Frame(card, style='Card.TFrame')
        row.pack(fill='x', pady=(0, 13))
        ttk.Label(row, text='01   PACKAGE QUEUE', style='Heading.TLabel').pack(side='left')
        self.clear_button = ttk.Button(row, text='Clear', style='Secondary.TButton', command=self._clear)
        self.clear_button.pack(side='right', padx=(7, 0))
        self.remove_button = ttk.Button(row, text='Remove selected', style='Secondary.TButton', command=self._remove)
        self.remove_button.pack(side='right', padx=(7, 0))
        self.folder_button = ttk.Button(row, text='+ Add folder', style='Secondary.TButton', command=self._add_folder)
        self.folder_button.pack(side='right', padx=(7, 0))
        self.add_button = ttk.Button(row, text='+ Add PKGs', style='Primary.TButton', command=self._add_dialog)
        self.add_button.pack(side='right', padx=(7, 0))

        table_container = ttk.Frame(card, style='Card.TFrame')
        table_container.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_container, columns=('filename', 'size', 'status', 'output'),
                                  show='headings', selectmode='extended', style='Pkg.Treeview', height=4)
        for key, title, width, stretch in [
            ('filename', 'Package', 310, True), ('size', 'Size', 105, False),
            ('status', 'Status', 110, False), ('output', 'Output folder', 310, True),
        ]:
            self.table.heading(key, text=title, anchor='w')
            self.table.column(key, width=width, stretch=stretch, anchor='w')
        self.table.tag_configure('done', foreground=SUCCESS)
        self.table.tag_configure('failed', foreground=ERROR)
        self.table.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table_container, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.bind('<Delete>', lambda _event: self._remove() if not self.running else None)
        self.table.bind('<Control-a>', self._select_all)
        self.table.bind('<Command-a>', self._select_all)
        ttk.Label(card, textvariable=self.summary_var, style='Muted.TLabel').pack(anchor='w', pady=(12, 0))

        self._enable_drop()

        config = ttk.Frame(shell, style='Card.TFrame', padding=14)
        config.pack(fill='x', pady=(0, 10))
        ttk.Label(config, text='02   EXTRACTION SETTINGS', style='Heading.TLabel').pack(anchor='w', pady=(0, 12))

        ttk.Label(config, text='Output directory', style='Muted.TLabel').pack(anchor='w')
        out_row = ttk.Frame(config, style='Card.TFrame')
        out_row.pack(fill='x', pady=(5, 12))
        self.output_entry = ttk.Entry(out_row, textvariable=self.output_var, style='App.TEntry')
        self.output_entry.pack(side='left', fill='x', expand=True, ipady=2)
        self.out_button = ttk.Button(out_row, text='Browse', style='Secondary.TButton', command=self._choose_output)
        self.out_button.pack(side='left', padx=(9, 0))
        ttk.Button(out_row, text='Open', style='Secondary.TButton', command=self._open_output).pack(side='left', padx=(9, 0))

        extractor_row = ttk.Frame(config, style='Card.TFrame')
        extractor_row.pack(fill='x')
        engine_col = ttk.Frame(extractor_row, style='Card.TFrame')
        engine_col.pack(side='left', padx=(0, 14))
        ttk.Label(engine_col, text='Extractor engine', style='Muted.TLabel').pack(anchor='w', pady=(0, 5))
        self.engine_select = ttk.Combobox(engine_col, state='readonly', style='App.TCombobox',
                                          textvariable=self.engine_var, width=24,
                                          values=list(ENGINE_LABELS.values()))
        self.engine_select.pack(fill='x', ipady=2)
        self.engine_select.bind('<<ComboboxSelected>>', self._on_engine_change)
        exe_col = ttk.Frame(extractor_row, style='Card.TFrame')
        exe_col.pack(side='left', fill='x', expand=True)
        ttk.Label(exe_col, text='Engine executable or PkgTool.Core.dll (bundled pkgextract is auto-detected)', style='Muted.TLabel').pack(anchor='w', pady=(0, 5))
        exe_row = ttk.Frame(exe_col, style='Card.TFrame')
        exe_row.pack(fill='x')
        self.exe_entry = ttk.Entry(exe_row, textvariable=self.exe_var, style='App.TEntry')
        self.exe_entry.pack(side='left', fill='x', expand=True, ipady=2)
        self.exe_button = ttk.Button(exe_row, text='Browse', style='Secondary.TButton', command=self._choose_exe)
        self.exe_button.pack(side='left', padx=(9, 0))

        footer = ttk.Frame(shell, style='Card.TFrame', padding=14)
        footer.pack(fill='x')
        action = ttk.Frame(footer, style='Card.TFrame')
        action.pack(fill='x')
        self.start_button = ttk.Button(action, text='Start extraction', style='Primary.TButton', command=self._start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(action, text='Cancel current run', style='Danger.TButton',
                                        state='disabled', command=self._cancel)
        self.cancel_button.pack(side='left', padx=(10, 0))
        self.retry_button = ttk.Button(action, text='Retry failed', style='Secondary.TButton',
                                       state='disabled', command=self._retry_failed)
        self.retry_button.pack(side='left', padx=(10, 0))
        self.export_button = ttk.Button(action, text='Save log', style='Secondary.TButton',
                                        command=self._export_log)
        self.export_button.pack(side='left', padx=(10, 0))
        ttk.Label(action, textvariable=self.progress_var, style='Card.TLabel').pack(side='right')
        self.progress_bar = ttk.Progressbar(footer, mode='determinate', maximum=1,
                                           style='Accent.Horizontal.TProgressbar')
        self.progress_bar.pack(fill='x', pady=(13, 7))
        ttk.Label(footer, textvariable=self.status_var, style='Muted.TLabel').pack(anchor='w', pady=(0, 8))
        ttk.Label(footer, text='EXTRACTION LOG', style='Heading.TLabel').pack(anchor='w', pady=(2, 4))
        ttk.Label(footer, textvariable=self.activity_var, style='Muted.TLabel').pack(anchor='w', pady=(0, 5))
        self.logs = scrolledtext.ScrolledText(footer, height=8, bg='#111b2b', fg=MUTED,
                                              insertbackground=INK, font=('Consolas' if os.name == 'nt' else 'Menlo' if sys.platform == 'darwin' else 'DejaVu Sans Mono', 9),
                                              wrap='word', relief='flat', state='disabled')
        self.logs.pack(fill='both', expand=True)
        self._write_log('Bundled pkgextract is selected when available; a compatible external engine can also be selected.')
        if self._pending_drop_error:
            self._write_log('Drag/drop unavailable; file picker still works.')

    def _shortcut_add(self, _event: tk.Event) -> str:
        if not self.running:
            self._add_dialog()
        return 'break'

    def _shortcut_add_folder(self, _event: tk.Event) -> str:
        if not self.running:
            self._add_folder()
        return 'break'

    def _schedule_preview_refresh(self, *_args: object) -> None:
        """Debounce expensive queue planning while the output path is typed."""
        if self._pending_preview_refresh is not None:
            self.root.after_cancel(self._pending_preview_refresh)
            self._pending_preview_refresh = None
        if not self.running:
            self._pending_preview_refresh = self.root.after(200, self._finish_preview_refresh)

    def _finish_preview_refresh(self) -> None:
        self._pending_preview_refresh = None
        if not self.running:
            self._refresh_table()

    def _enable_drop(self) -> None:
        if DND_FILES is None:
            return
        try:
            self.table.drop_target_register(DND_FILES)
            self.table.dnd_bind('<<Drop>>', self._on_drop)
        except (tk.TclError, AttributeError, OSError):
            self._pending_drop_error = True

    def _on_drop(self, event) -> None:
        if self.running:
            return
        try:
            dropped = [Path(item) for item in self.root.tk.splitlist(event.data)]
        except (ValueError, tk.TclError):
            return
        paths = []
        for path in dropped:
            if path.is_file():
                paths.append(path)
            elif path.is_dir():
                try:
                    paths.extend(scan_folder(path))
                except OSError:
                    pass
        self._append_sources(paths)

    def _select_all(self, _event) -> str:
        self.table.selection_set(*self.table.get_children())
        return 'break'

    def _add_dialog(self) -> None:
        paths = filedialog.askopenfilenames(title='Select one or more PS4 PKG files',
                                             filetypes=[('PS4 packages', '*.pkg'), ('All files', '*.*')])
        if paths:
            self._append_sources(Path(p) for p in paths)

    def _add_folder(self) -> None:
        name = filedialog.askdirectory(title='Add all PKG files from folder')
        if not name:
            return
        try:
            paths = scan_folder(Path(name))
        except OSError as exc:
            messagebox.showerror('Folder error', str(exc), parent=self.root)
            return
        self._append_sources(paths)
        if not paths:
            self.status_var.set('No .pkg files found directly inside that folder.')

    def _append_sources(self, paths: Iterable[Path]) -> None:
        old_count = len(self.sources)
        self.sources = collect_pkgs(self.sources + list(paths))
        self._refresh_table()
        self.status_var.set(f'Added {len(self.sources) - old_count} package(s).')

    def _remove(self) -> None:
        if self.running:
            return
        selected = {int(row) for row in self.table.selection()}
        self.sources = [p for i, p in enumerate(self.sources) if i not in selected]
        self.failed_sources = [p for p in self.failed_sources if p in self.sources]
        self._refresh_table()
        self._sync_retry_button()

    def _clear(self) -> None:
        if self.running:
            return
        self.sources.clear()
        self.failed_sources.clear()
        self._refresh_table()
        self._sync_retry_button()

    def _sync_retry_button(self) -> None:
        self.retry_button.configure(state='normal' if not self.running and self.failed_sources else 'disabled')

    def _configure_batch_progress(self, package_count: int, completed: int = 0) -> None:
        """Configure exact package-level progress without an animated marquee."""
        self.progress_bar.configure(
            mode='determinate', maximum=max(1, package_count), value=completed
        )

    def _refresh_table(self) -> None:
        if self.running:
            return
        if self._pending_preview_refresh is not None:
            self.root.after_cancel(self._pending_preview_refresh)
            self._pending_preview_refresh = None
        for row in self.table.get_children():
            self.table.delete(row)
        self.rows.clear()
        output = Path(self.output_var.get().strip() or Path.home() / 'Extracted-PKG')
        self.current_jobs = plan_jobs(self.sources, output)
        total_size = 0
        for number, job in enumerate(self.current_jobs):
            try:
                size = job.source.stat().st_size
            except OSError:
                size = 0
            total_size += size
            row_id = str(number)
            self.table.insert('', 'end', iid=row_id,
                              values=(job.source.name, format_bytes(size), 'Queued', job.destination.name))
            self.rows.append(row_id)
        self.summary_var.set(f'{len(self.current_jobs)} package(s)  •  {format_bytes(total_size)} total input')
        self._configure_batch_progress(len(self.sources))
        self.progress_var.set(f'0 / {len(self.sources)} completed')

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title='Choose where to extract packages')
        if path:
            self.output_var.set(path)

    def _choose_exe(self) -> None:
        # Native binaries typically have no extension on Linux/macOS.
        filters = ([('Executable or DLL', '*.exe *.dll'), ('All files', '*.*')]
                   if os.name == 'nt' else [('All files', '*')])
        path = filedialog.askopenfilename(title='Select extractor executable', filetypes=filters)
        if path:
            self.exe_var.set(path)

    def _on_engine_change(self, _event) -> None:
        kind = self._selected_kind()
        detected = discover_executable(kind)
        self.exe_var.set(str(detected) if detected else '')

    def _selected_kind(self) -> str:
        return next((kind for kind, label in ENGINE_LABELS.items() if label == self.engine_var.get()), 'pkgextract')

    def _open_output(self) -> None:
        path = Path(self.output_var.get().strip()).expanduser()
        if not path.is_dir():
            messagebox.showinfo('Output not found', 'The output directory does not exist yet.', parent=self.root)
            return
        try:
            if os.name == 'nt':
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(path)])
            else:
                subprocess.Popen(['xdg-open', str(path)])
        except (OSError, ValueError) as exc:
            messagebox.showerror('Open folder failed', str(exc), parent=self.root)

    def _warn_if_low_disk_space(self, output: Path, jobs) -> None:
        required = estimate_required_disk_bytes(jobs)
        free = shutil.disk_usage(output).free
        if free >= required:
            return
        warning = (
            f'The selected drive has {format_bytes(free)} free. '
            f'The estimated space needed is about {format_bytes(required)}.\n\n'
            'This is a rough estimate based on the PKG sizes; compressed packages may need more space. '
            'The extraction will continue, but it may fail if the files expand beyond the available space.'
        )
        self._write_log(f'Low disk space warning: {format_bytes(free)} free; estimated need {format_bytes(required)}.')
        messagebox.showwarning('Low disk space', warning, parent=self.root)

    def _notify_success(self, done: int, failed: int, cancelled: bool) -> None:
        if done > 0 and failed == 0 and not cancelled:
            messagebox.showinfo(
                'Extraction complete',
                f'Successfully extracted {done} package(s).\n\nOutput folder:\n{self.output_var.get()}',
                parent=self.root,
            )

    def _start(self) -> None:
        if self.running or self.runner.active:
            return
        if not self.current_jobs:
            messagebox.showinfo('No packages', 'Add at least one .pkg file.', parent=self.root)
            return
        try:
            exe_value = self.exe_var.get().strip().strip('"')
            if not exe_value:
                raise ValueError('Choose the engine executable first. See README.md.')
            extractor = Extractor(self._selected_kind(), Path(exe_value).expanduser())
            extractor.validate()
            output = Path(self.output_var.get().strip()).expanduser().resolve(strict=False)
            if output.exists() and not output.is_dir():
                raise ValueError('Output path is not a directory.')
            output.mkdir(parents=True, exist_ok=True)
            if not os.access(output, os.W_OK):
                raise PermissionError('Output directory is not writable.')
            jobs = plan_jobs(self.sources, output)
            if len(jobs) != len(self.sources):
                raise ValueError('Some selected files are missing. Remove and re-add them.')
            self._warn_if_low_disk_space(output, jobs)
            save_settings(self._selected_kind(), str(extractor.executable), str(output))
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cannot start extraction', str(exc), parent=self.root)
            return
        self.failed_sources = []
        self._refresh_table()  # Show final planned output names.
        self.current_jobs = jobs
        self.running = True
        self._set_controls(False)
        # The bundled engine doesn't expose a machine-readable per-file byte
        # total. Keep this determinate at the exact batch/package level instead
        # of showing a bouncing indeterminate block or inventing a percentage.
        self._configure_batch_progress(len(jobs))
        self.progress_var.set(f'0 / {len(jobs)} completed')
        self.activity_var.set('Starting extractor; waiting for output files...')
        self.status_var.set('Extracting. The current package may take some time...')
        self._write_log(f'Batch started with {len(jobs)} package(s).')
        try:
            self.runner.start(jobs, extractor)
        except RuntimeError as exc:
            self.running = False
            self.progress_bar.stop()
            self.progress_bar.configure(mode='determinate', value=0)
            self._set_controls(True)
            messagebox.showerror('Cannot start extraction', str(exc), parent=self.root)

    def _retry_failed(self) -> None:
        if self.running or not self.failed_sources:
            return
        failed = list(self.failed_sources)
        self.sources = collect_pkgs(failed)
        self.failed_sources = []
        self._sync_retry_button()
        self._refresh_table()
        self._start()

    def _export_log(self) -> None:
        filename = filedialog.asksaveasfilename(
            title='Save extraction log', defaultextension='.txt',
            filetypes=[('Text log', '*.txt'), ('All files', '*.*')],
            initialfile='pkg-batch-extractor.log', parent=self.root,
        )
        if not filename:
            return
        try:
            Path(filename).write_text('\n'.join(self.log_history) + '\n', encoding='utf-8')
        except OSError as exc:
            messagebox.showerror('Cannot save log', str(exc), parent=self.root)
        else:
            self.status_var.set(f'Log saved to {filename}')

    def _cancel(self) -> None:
        if self.running:
            self.runner.cancel()
            self.cancel_button.configure(state='disabled')
            self.status_var.set('Cancelling current extraction...')

    def _set_controls(self, enabled: bool) -> None:
        state = 'normal' if enabled else 'disabled'
        for button in (self.add_button, self.folder_button, self.clear_button,
                       self.remove_button, self.out_button, self.exe_button, self.start_button):
            button.configure(state=state)
        for entry in (self.exe_entry, self.output_entry):
            entry.configure(state=state)
        self.engine_select.configure(state='readonly' if enabled else 'disabled')
        self.cancel_button.configure(state='disabled' if enabled else 'normal')
        self.retry_button.configure(state='normal' if enabled and self.failed_sources else 'disabled')

    def _pump_events(self) -> None:
        try:
            for _ in range(MAX_UI_EVENTS_PER_TICK):
                event = self.events.get_nowait()
                kind = event[0]
                if kind == 'log':
                    self._write_log(str(event[1]))
                elif kind == 'status':
                    _, idx, status, extra = event
                    if status == 'Failed' and 0 <= idx < len(self.current_jobs):
                        source = self.current_jobs[idx].source
                        if source not in self.failed_sources:
                            self.failed_sources.append(source)
                    row = str(idx)
                    if self.table.exists(row):
                        values = list(self.table.item(row, 'values'))
                        values[2] = status
                        if status == 'Completed' and extra:
                            values[3] = Path(extra).name
                        self.table.item(row, values=values,
                                        tags=('done',) if status == 'Completed' else
                                             ('failed',) if status == 'Failed' else ())
                    if status in ('Failed', 'Cancelled') and extra:
                        self._write_log(f'{status}: {extra}')
                    elif status == 'Extracting':
                        self.progress_var.set(
                            f'Extracting package {idx + 1} of {len(self.current_jobs)}'
                        )
                elif kind == 'progress':
                    _, visited, total, done, failed = event
                    self.progress_bar.configure(value=visited)
                    self.progress_var.set(f'{done} completed / {total}  •  {failed} failed')
                    self.status_var.set(f'Processed {visited} of {total} packages.')
                elif kind == 'metrics':
                    _, name, file_count, byte_count, elapsed, speed = event
                    duration = f'{elapsed // 60:02d}:{elapsed % 60:02d}'
                    speed_text = f' • {speed / (1024 * 1024):.2f} MB/s' if speed is not None else ''
                    self.activity_var.set(
                        f'{name}: {file_count:,} files • {format_bytes(byte_count)} extracted{speed_text} • {duration} elapsed'
                    )
                    self.status_var.set(f'Extracting {name} — {file_count:,} files, {format_bytes(byte_count)}')
                elif kind == 'finished':
                    _, done, failed, cancelled = event
                    self.running = False
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode='determinate',
                                                maximum=max(1, len(self.current_jobs)),
                                                value=len(self.current_jobs) if not cancelled else done + failed)
                    self._set_controls(True)
                    result = 'Cancelled' if cancelled else 'Finished'
                    self.status_var.set(f'{result}: {done} extracted, {failed} failed.')
                    if cancelled:
                        self._write_log('Extraction cancelled.')
                    elif failed:
                        self._write_log('Extraction finished with errors.')
                    else:
                        self._write_log('Extraction finished successfully.')
                    self._write_log(f'{result}: {done} completed, {failed} failed.')
                    if self._close_after_run:
                        self._save_and_close()
                        return
                    self._notify_success(done, failed, cancelled)
        except queue.Empty:
            pass
        # Drain large logs over multiple Tk ticks, giving interaction a chance to run.
        self.root.after(1 if not self.events.empty() else 120, self._pump_events)

    def _write_log(self, message: str) -> None:
        self.log_history.append(message)
        # Widget exists before this function runs except optional drop errors, which run later.
        self.logs.configure(state='normal')
        self.logs.insert('end', message + '\n')
        self._visible_log_lines += 1
        if self._visible_log_lines > MAX_VISIBLE_LOG_LINES:
            # Trim in chunks instead of scanning the Tk text widget on each event.
            self.logs.delete('1.0', '101.0')
            self._visible_log_lines -= 100
        self.logs.see('end')
        self.logs.yview_moveto(1.0)
        self.logs.configure(state='disabled')

    def _save_and_close(self) -> None:
        if self._pending_preview_refresh is not None:
            self.root.after_cancel(self._pending_preview_refresh)
            self._pending_preview_refresh = None
        try:
            save_settings(self._selected_kind(), self.exe_var.get().strip(), self.output_var.get().strip())
        except OSError:
            pass
        self.root.destroy()

    def _on_close(self) -> None:
        if self.running:
            leave = messagebox.askyesno(
                'Extraction in progress',
                'An extraction is still running. Do you want to cancel it and exit after it stops?',
                parent=self.root, default=messagebox.NO,
            )
            if leave:
                self._close_after_run = True
                self._cancel()
            return
        self._save_and_close()


def main() -> None:
    if TkinterDnD is None:
        root = tk.Tk()
    else:
        try:
            root = TkinterDnD.Tk()
        except (tk.TclError, OSError):
            # A native TkDnD library may be missing on some distributions.
            root = tk.Tk()
    App(root)
    root.mainloop()
