"""Tkinter desktop app for kbparser."""
from __future__ import annotations

import io
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from functools import partial
from pathlib import Path
from typing import Any

from . import __version__
from .cli import main as cli_main
from .runtime_tools import app_tools_dir, dependency_download_links, dependency_guidance_text, dependency_status_text

PROFILES = ("fidelity", "balanced", "text-lite")
OUTPUT_FORMATS = ("both", "md", "json")
STATUSES = {"processing": "Обработка", "success": "Готово", "partial": "Проверить",
            "skipped": "Уже готово", "failed": "Ошибка", "cancelled": "Отменено"}


class _LogStream(io.TextIOBase):
    def __init__(self, messages: queue.Queue):
        self.messages = messages

    def write(self, text: str) -> int:
        if text:
            self.messages.put(("log", text))
        return len(text)

    def flush(self) -> None:
        pass


def build_parse_args(
    *,
    source: Path,
    output_dir: Path | None,
    profile: str,
    ocr_langs: str,
    output_format: str,
    overwrite: bool,
) -> list[str]:
    args = ["parse", str(source)]
    if output_dir is not None:
        args.extend(["--out", str(output_dir)])
    args.extend(["--profile", profile])
    lang = ocr_langs.strip()
    if lang:
        args.extend(["--lang", lang])
    args.extend(["--format", output_format])
    if overwrite:
        args.append("--overwrite")
    return args


def default_output_dir(source: Path) -> Path:
    return source.parent / "kb-parse-out"


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
        return
    subprocess.run(["xdg-open", str(path)], check=False)


def open_tools_folder() -> None:
    folder = app_tools_dir()
    folder.mkdir(parents=True, exist_ok=True)
    open_path(folder)


def setup_tools_text() -> str:
    return "\n\n".join(
        [
            dependency_status_text(),
            f"User tools folder:\n{app_tools_dir()}",
            dependency_guidance_text(),
        ]
    )


class KBParserApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.busy = False
        self.last_output_dir: Path | None = None

        root.title(f"KB Parser {__version__}")
        root.minsize(920, 680)
        root.protocol("WM_DELETE_WINDOW", self.close)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.profile_var = tk.StringVar(value="fidelity")
        self.lang_var = tk.StringVar(value="rus+eng")
        self.output_format_var = tk.StringVar(value="both")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Готов к работе")

        main = ttk.Frame(root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(7, weight=1)
        main.rowconfigure(9, weight=1)

        ttk.Label(main, text="Источник").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(main, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 6))
        ttk.Button(main, text="Файл", command=self.browse_file).grid(row=0, column=2, padx=(0, 6), pady=(0, 6))
        ttk.Button(main, text="Папка", command=self.browse_folder).grid(row=0, column=3, pady=(0, 6))

        ttk.Label(main, text="Результат").grid(row=1, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(main, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 6))
        ttk.Button(main, text="Выбрать", command=self.browse_output).grid(row=1, column=2, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(main, text="Режим").grid(row=2, column=0, sticky="w", pady=(0, 6))
        ttk.OptionMenu(main, self.profile_var, self.profile_var.get(), *PROFILES).grid(
            row=2, column=1, sticky="w", padx=8, pady=(0, 6)
        )

        ttk.Label(main, text="Языки OCR").grid(row=3, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(main, textvariable=self.lang_var, width=18).grid(row=3, column=1, sticky="w", padx=8, pady=(0, 6))
        ttk.Checkbutton(main, text="Перезаписать результат", variable=self.overwrite_var).grid(
            row=3, column=2, columnspan=2, sticky="w", pady=(0, 6)
        )

        ttk.Label(main, text="Формат").grid(row=4, column=0, sticky="w", pady=(0, 6))
        ttk.OptionMenu(main, self.output_format_var, self.output_format_var.get(), *OUTPUT_FORMATS).grid(
            row=4, column=1, sticky="w", padx=8, pady=(0, 6)
        )

        actions = ttk.Frame(main)
        actions.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(6, 10))
        actions.columnconfigure(4, weight=1)
        self.parse_button = ttk.Button(actions, text="Обработать", command=self.parse)
        self.parse_button.grid(row=0, column=0, padx=(0, 8))
        self.doctor_button = ttk.Button(actions, text="Диагностика", command=self.doctor)
        self.doctor_button.grid(row=0, column=1, padx=(0, 8))
        self.setup_button = ttk.Button(actions, text="Инструменты", command=self.show_setup_tools)
        self.setup_button.grid(row=0, column=2, padx=(0, 8))
        self.open_button = ttk.Button(actions, text="Открыть папку", command=self.open_output, state="disabled")
        self.open_button.grid(row=0, column=3, padx=(0, 8))
        self.cancel_button = ttk.Button(actions, text="Отменить", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=0, column=4, sticky="w")
        self.preview_button = ttk.Button(actions, text="Просмотр", command=self.preview, state="disabled")
        self.preview_button.grid(row=0, column=5, padx=(8, 0))
        ttk.Label(main, textvariable=self.status_var).grid(row=6, column=0, columnspan=2, sticky="w")
        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.grid(row=6, column=2, columnspan=2, sticky="ew", pady=6)
        self.files = ttk.Treeview(main, columns=("file", "status", "records"), show="headings", height=6)
        for name, title in [("file", "Файл"), ("status", "Состояние"), ("records", "Фрагменты")]:
            self.files.heading(name, text=title)
        self.files.column("file", width=560)
        self.files.column("status", width=120)
        self.files.column("records", width=85)
        self.files.grid(row=7, column=0, columnspan=4, sticky="nsew", pady=8)
        ttk.Label(main, text="Журнал").grid(row=8, column=0, sticky="w")
        self.log = tk.Text(main, height=10, wrap="word", state="disabled")
        self.log.grid(row=9, column=0, columnspan=4, sticky="nsew")
        scroll = ttk.Scrollbar(main, orient="vertical", command=self.log.yview)
        scroll.grid(row=9, column=4, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        menu = tk.Menu(root)
        file_menu = tk.Menu(menu, tearoff=False)
        for label, command in [
            ("Открыть файл…", self.browse_file), ("Открыть папку…", self.browse_folder),
            ("Выбрать папку результата…", self.browse_output), ("Обработать", self.parse),
            ("Отменить обработку", self.cancel), ("Просмотр результата…", self.preview),
            ("Диагностика", self.doctor), ("Закрыть", self.close),
        ]:
            file_menu.add_command(label=label, command=command)
        menu.add_cascade(label="Файл", menu=file_menu)
        root.configure(menu=menu)

        self.root.after(100, self.poll_worker)

    def browse_file(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            filetypes=[
                ("Supported documents", "*.pdf *.docx *.doc *.xlsx *.xls"),
                ("All files", "*.*"),
            ]
        )
        if path:
            self.set_source(Path(path))

    def browse_folder(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory()
        if path:
            self.set_source(Path(path))

    def browse_output(self) -> None:
        from tkinter import filedialog

        path = filedialog.askdirectory()
        if path:
            self.output_var.set(path)

    def set_source(self, path: Path) -> None:
        self.source_var.set(str(path))
        if not self.output_var.get().strip():
            self.output_var.set(str(default_output_dir(path)))

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 2000:
            self.log.delete("1.0", f"{lines - 2000}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def doctor(self) -> None:
        self.start_worker(["doctor"], Path.cwd())

    def show_setup_tools(self) -> None:
        self.doctor()
        win = self.tk.Toplevel(self.root)
        win.title("Setup tools")
        win.minsize(680, 480)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

        body = self.ttk.Frame(win, padding=14)
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        text = self.tk.Text(body, wrap="word", height=20)
        text.insert("1.0", dependency_guidance_text() + f"\n\nПапка инструментов:\n{app_tools_dir()}")
        text.configure(state="disabled")
        text.grid(row=0, column=0, sticky="nsew")
        scroll = self.ttk.Scrollbar(body, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)

        links = self.ttk.Frame(body)
        links.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.ttk.Button(links, text="Open tools folder", command=open_tools_folder).grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 8),
        )
        for col, (label, url) in enumerate(dependency_download_links()):
            grid_col = col + 1
            links.columnconfigure(grid_col, weight=1)
            self.ttk.Button(links, text=label, command=partial(webbrowser.open, url)).grid(
                row=0,
                column=grid_col,
                sticky="ew",
                padx=(0, 8 if col < 2 else 0),
            )

    def parse(self) -> None:
        from tkinter import messagebox

        raw_source = self.source_var.get().strip()
        if not raw_source:
            messagebox.showerror("Missing source", "Choose a file or folder first.")
            return
        source = Path(raw_source).expanduser()
        if not source.exists():
            messagebox.showerror("Source not found", str(source))
            return

        output_raw = self.output_var.get().strip()
        output_dir = Path(output_raw).expanduser() if output_raw else None
        args = build_parse_args(
            source=source,
            output_dir=output_dir,
            profile=self.profile_var.get(),
            ocr_langs=self.lang_var.get(),
            output_format=self.output_format_var.get(),
            overwrite=self.overwrite_var.get(),
        )
        self.start_worker(args, output_dir or default_output_dir(source))

    def start_worker(self, args: list[str], output_dir: Path) -> None:
        if self.busy:
            return
        self.busy = True
        self.cancel_event.clear()
        self.parse_button.configure(state="disabled")
        self.doctor_button.configure(state="disabled")
        self.setup_button.configure(state="disabled")
        self.cancel_button.configure(state="normal" if args[0] == "parse" else "disabled")
        self.status_var.set("Обработка…" if args[0] == "parse" else "Проверка окружения…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(80)
        if args[0] == "parse":
            for item in self.files.get_children():
                self.files.delete(item)
        self.append_log("$ kbparser " + " ".join(args) + "\n")
        thread = threading.Thread(target=self.run_cli, args=(args, output_dir), daemon=True)
        thread.start()

    def run_cli(self, args: list[str], output_dir: Path) -> None:
        stream = _LogStream(self.queue)
        code = 1
        try:
            with redirect_stdout(stream), redirect_stderr(stream):
                code = cli_main(args, cancelled=self.cancel_event.is_set,
                                progress=lambda event: self.queue.put(("file", event)))
        except Exception as exc:  # keep GUI alive on parser bugs
            stream.write(f"{type(exc).__name__}: {exc}\n")
        self.queue.put(("done", {"code": code, "output_dir": output_dir if args[0] == "parse" else None}))

    def poll_worker(self) -> None:
        for _ in range(100):
            try:
                kind, data = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.append_log(data)
            elif kind == "file":
                iid = str(data["index"])
                values = (Path(data["file"]).name, STATUSES[data["status"]], data.get("records", ""))
                if self.files.exists(iid):
                    self.files.item(iid, values=values)
                else:
                    self.files.insert("", "end", iid=iid, values=values)
                self.files.see(iid)
                if data["status"] == "processing":
                    self.status_var.set(f"Файл {data['index'] + 1} из {data['total']}: {Path(data['file']).name}")
            elif kind == "done":
                self.busy = False
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=1, value=1 if data["code"] == 0 else 0)
                for button in (self.parse_button, self.doctor_button, self.setup_button):
                    button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                if data["output_dir"] is not None:
                    self.last_output_dir = data["output_dir"]
                    self.open_button.configure(state="normal")
                    self.preview_button.configure(state="normal")
                status = {0: "Обработка завершена", 130: "Обработка отменена"}.get(data["code"], f"Ошибка ({data['code']})")
                self.status_var.set(status)
        self.root.after(100, self.poll_worker)

    def cancel(self) -> None:
        if not self.busy:
            return
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status_var.set("Остановка после текущей операции…")

    def close(self) -> None:
        self.cancel_event.set()
        self.root.destroy()

    def preview(self) -> None:
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(initialdir=self.last_output_dir,
                                         filetypes=[("Markdown / JSON", "*.md *.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as stream:
                content = stream.read(200001)
        except OSError as exc:
            messagebox.showerror("Не удалось открыть результат", str(exc))
            return
        win = self.tk.Toplevel(self.root)
        win.title(Path(path).name)
        text = self.tk.Text(win, wrap="word", width=110, height=35, padx=12, pady=12)
        scroll = self.ttk.Scrollbar(win, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.insert("1.0", content[:200000] + ("\n\n[Показаны первые 200 000 символов]" if len(content) > 200000 else ""))
        text.configure(state="disabled")

    def open_output(self) -> None:
        if self.last_output_dir is not None:
            open_path(self.last_output_dir)


def main() -> int:
    import tkinter as tk

    root = tk.Tk()
    KBParserApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
