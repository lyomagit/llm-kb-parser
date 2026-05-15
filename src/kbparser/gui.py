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
from pathlib import Path

from . import __version__
from .cli import main as cli_main
from .runtime_tools import dependency_download_links, dependency_guidance_text

PROFILES = ("fidelity", "balanced", "text-lite")


def build_parse_args(
    *,
    source: Path,
    output_dir: Path | None,
    profile: str,
    ocr_langs: str,
    overwrite: bool,
) -> list[str]:
    args = ["parse", str(source)]
    if output_dir is not None:
        args.extend(["--out", str(output_dir)])
    args.extend(["--profile", profile])
    lang = ocr_langs.strip()
    if lang:
        args.extend(["--lang", lang])
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


class KBParserApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.queue: queue.Queue[tuple[int, str, Path]] = queue.Queue()
        self.last_output_dir: Path | None = None

        root.title(f"KB Parser {__version__}")
        root.minsize(780, 560)

        self.source_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.profile_var = tk.StringVar(value="fidelity")
        self.lang_var = tk.StringVar(value="rus+eng")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")

        main = ttk.Frame(root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(7, weight=1)

        ttk.Label(main, text="Source").grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(main, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=8, pady=(0, 6))
        ttk.Button(main, text="File", command=self.browse_file).grid(row=0, column=2, padx=(0, 6), pady=(0, 6))
        ttk.Button(main, text="Folder", command=self.browse_folder).grid(row=0, column=3, pady=(0, 6))

        ttk.Label(main, text="Output").grid(row=1, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(main, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 6))
        ttk.Button(main, text="Choose", command=self.browse_output).grid(row=1, column=2, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(main, text="Profile").grid(row=2, column=0, sticky="w", pady=(0, 6))
        ttk.OptionMenu(main, self.profile_var, self.profile_var.get(), *PROFILES).grid(
            row=2, column=1, sticky="w", padx=8, pady=(0, 6)
        )

        ttk.Label(main, text="OCR language").grid(row=3, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(main, textvariable=self.lang_var, width=18).grid(row=3, column=1, sticky="w", padx=8, pady=(0, 6))
        ttk.Checkbutton(main, text="Overwrite existing output", variable=self.overwrite_var).grid(
            row=3, column=2, columnspan=2, sticky="w", pady=(0, 6)
        )

        actions = ttk.Frame(main)
        actions.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 10))
        actions.columnconfigure(4, weight=1)
        self.parse_button = ttk.Button(actions, text="Parse", command=self.parse)
        self.parse_button.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(actions, text="Doctor", command=self.doctor).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(actions, text="Setup tools", command=self.show_setup_tools).grid(row=0, column=2, padx=(0, 8))
        self.open_button = ttk.Button(actions, text="Open output", command=self.open_output, state="disabled")
        self.open_button.grid(row=0, column=3, padx=(0, 8))
        ttk.Label(actions, textvariable=self.status_var).grid(row=0, column=4, sticky="e")

        ttk.Label(main, text="Log").grid(row=6, column=0, sticky="w")
        self.log = tk.Text(main, height=18, wrap="word")
        self.log.grid(row=7, column=0, columnspan=4, sticky="nsew")
        scroll = ttk.Scrollbar(main, orient="vertical", command=self.log.yview)
        scroll.grid(row=7, column=4, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

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
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")

    def doctor(self) -> None:
        self.start_worker(["doctor"], Path.cwd())

    def show_setup_tools(self) -> None:
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
        text.insert("1.0", dependency_guidance_text())
        text.configure(state="disabled")
        text.grid(row=0, column=0, sticky="nsew")
        scroll = self.ttk.Scrollbar(body, orient="vertical", command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)

        links = self.ttk.Frame(body)
        links.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for col, (label, url) in enumerate(dependency_download_links()):
            links.columnconfigure(col, weight=1)
            self.ttk.Button(links, text=label, command=lambda u=url: webbrowser.open(u)).grid(
                row=0,
                column=col,
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
            overwrite=self.overwrite_var.get(),
        )
        self.start_worker(args, output_dir or default_output_dir(source))

    def start_worker(self, args: list[str], output_dir: Path) -> None:
        self.parse_button.configure(state="disabled")
        self.status_var.set("Running...")
        self.append_log("$ kbparser " + " ".join(args))
        thread = threading.Thread(target=self.run_cli, args=(args, output_dir), daemon=True)
        thread.start()

    def run_cli(self, args: list[str], output_dir: Path) -> None:
        stream = io.StringIO()
        code = 1
        try:
            with redirect_stdout(stream), redirect_stderr(stream):
                code = cli_main(args)
        except Exception as exc:  # keep GUI alive on parser bugs
            stream.write(f"{type(exc).__name__}: {exc}\n")
        self.queue.put((code, stream.getvalue(), output_dir))

    def poll_worker(self) -> None:
        try:
            code, text, output_dir = self.queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self.poll_worker)
            return

        self.append_log(text or "(no output)")
        self.parse_button.configure(state="normal")
        self.last_output_dir = output_dir
        self.open_button.configure(state="normal")
        self.status_var.set("Finished" if code == 0 else f"Failed ({code})")
        self.root.after(100, self.poll_worker)

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
