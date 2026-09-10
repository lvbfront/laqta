from __future__ import annotations

import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from laqta_agent import keychain
from laqta_agent.api_client import ApiClient, NetworkError, PairingError, ServerError
from laqta_agent.config import APP_NAME, queue_db_path
from laqta_agent.i18n import t
from laqta_agent.queue_db import UploadQueue
from laqta_agent.settings import Settings, load_settings, save_settings
from laqta_agent.uploader import Uploader
from laqta_agent.watcher import FolderWatcher

# tkinter has no real bidi/logical-RTL layout engine the way a browser
# does -- there's no equivalent of CSS's dir="rtl" that reorders and
# mirrors a whole widget tree. Arabic mode here means right-aligned text
# (justify="right") on every label, which reads correctly, rather than a
# fully mirrored window layout. Noted so this isn't mistaken for an
# oversight later.
STATUS_POLL_MS = 1000


class AgentApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.settings = load_settings()
        self.locale = self.settings.locale
        self.api_client = ApiClient()
        self.queue = UploadQueue(queue_db_path())
        self.token: str | None = None
        self.event_id: str | None = None
        self.watcher: FolderWatcher | None = None
        self.uploader: Uploader | None = None

        self.root.title(t(self.locale, "app.title"))
        self.root.geometry("480x460")
        self.root.minsize(420, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.pairing_frame = ttk.Frame(self.root, padding=24)
        self.status_frame = ttk.Frame(self.root, padding=16)

        self._build_pairing_frame()
        self._build_status_frame()

        existing = keychain.load_token()
        if existing:
            self.token, self.event_id = existing
            self._start_background_work()
            self._show_status()
        else:
            self._show_pairing()

    # ------------------------------------------------------------------
    # Pairing screen
    # ------------------------------------------------------------------
    def _build_pairing_frame(self) -> None:
        f = self.pairing_frame
        self.pairing_title = ttk.Label(f, text=t(self.locale, "pair.title"), font=("", 16, "bold"))
        self.pairing_title.pack(pady=(0, 8))
        self.pairing_instructions = ttk.Label(
            f, text=t(self.locale, "pair.instructions"), wraplength=380, justify="right"
        )
        self.pairing_instructions.pack(pady=(0, 16))

        self.code_var = tk.StringVar()
        self.code_entry = ttk.Entry(f, textvariable=self.code_var, font=("", 22), justify="center", width=10)
        self.code_entry.pack(pady=(0, 16))
        self.code_entry.bind("<Return>", lambda _e: self._on_pair_submit())
        # A photographer copy-pasting or reading the code aloud shouldn't
        # have to worry about case -- the API already normalizes this too
        # (app.services.agent_pairing.redeem_pairing_code), this is just
        # so what they see matches what the dashboard showed them.
        self.code_var.trace_add("write", lambda *_a: self.code_var.set(self.code_var.get().upper()))

        self.pair_button = ttk.Button(f, text=t(self.locale, "pair.submit"), command=self._on_pair_submit)
        self.pair_button.pack(pady=(0, 16))

        self.pairing_locale_button = ttk.Button(f, text=t(self.locale, "locale.toggle"), command=self._toggle_locale)
        self.pairing_locale_button.pack()

    def _on_pair_submit(self) -> None:
        code = self.code_var.get().strip()
        if not code:
            return
        self.pair_button.configure(state="disabled", text=t(self.locale, "pair.pairing"))
        threading.Thread(target=self._pair_worker, args=(code,), daemon=True).start()

    def _pair_worker(self, code: str) -> None:
        try:
            token, event_id = self.api_client.pair(code, device_label=socket.gethostname())
        except PairingError:
            self.root.after(0, self._pair_failed, t(self.locale, "pair.error_invalid"))
            return
        except NetworkError:
            self.root.after(0, self._pair_failed, t(self.locale, "pair.error_network"))
            return
        except ServerError:
            self.root.after(0, self._pair_failed, t(self.locale, "pair.error_server"))
            return

        keychain.save_token(token, event_id)
        self.token, self.event_id = token, event_id
        self.root.after(0, self._after_paired)

    def _pair_failed(self, message: str) -> None:
        self.pair_button.configure(state="normal", text=t(self.locale, "pair.submit"))
        messagebox.showerror(t(self.locale, "pair.title"), message)

    def _after_paired(self) -> None:
        self.pair_button.configure(state="normal", text=t(self.locale, "pair.submit"))
        if self.settings.folder and Path(self.settings.folder).is_dir():
            self._start_background_work()
            self._show_status()
        else:
            self._choose_folder(first_time=True)

    # ------------------------------------------------------------------
    # Folder selection
    # ------------------------------------------------------------------
    def _choose_folder(self, first_time: bool = False) -> None:
        if first_time:
            messagebox.showinfo(t(self.locale, "folder.title"), t(self.locale, "folder.instructions"))
        chosen = filedialog.askdirectory(title=t(self.locale, "folder.title"))
        if not chosen:
            if first_time:
                # Can't proceed without a folder -- ask again rather than
                # leaving the agent in a half-configured state.
                self.root.after(300, lambda: self._choose_folder(first_time=True))
            return
        self.settings.folder = chosen
        save_settings(self.settings)
        self._restart_watcher()
        self._show_status()

    # ------------------------------------------------------------------
    # Status screen
    # ------------------------------------------------------------------
    def _build_status_frame(self) -> None:
        f = self.status_frame

        top = ttk.Frame(f)
        top.pack(fill="x")
        self.connection_label = ttk.Label(top, text="", font=("", 13, "bold"))
        self.connection_label.pack(side="left")
        self.status_locale_button = ttk.Button(top, text=t(self.locale, "locale.toggle"), command=self._toggle_locale)
        self.status_locale_button.pack(side="right")

        folder_row = ttk.Frame(f)
        folder_row.pack(fill="x", pady=(12, 0))
        self.folder_label = ttk.Label(folder_row, text="", wraplength=340, justify="right")
        self.folder_label.pack(side="left", fill="x", expand=True)
        self.change_folder_button = ttk.Button(
            folder_row, text=t(self.locale, "folder.change"), command=lambda: self._choose_folder(first_time=False)
        )
        self.change_folder_button.pack(side="right")

        counts_frame = ttk.Frame(f)
        counts_frame.pack(fill="x", pady=16)
        self.uploaded_label = ttk.Label(counts_frame, text="", font=("", 11))
        self.uploaded_label.pack(anchor="e")
        self.queued_label = ttk.Label(counts_frame, text="", font=("", 11))
        self.queued_label.pack(anchor="e")
        self.failed_label = ttk.Label(counts_frame, text="", font=("", 11))
        self.failed_label.pack(anchor="e")

        self.catch_up_button = ttk.Button(f, text=t(self.locale, "status.catch_up"), command=self._on_catch_up)
        self.catch_up_button.pack(fill="x", pady=(0, 12))

        self.errors_title_label = ttk.Label(f, text=t(self.locale, "status.errors_title"), font=("", 11, "bold"))
        self.errors_title_label.pack(anchor="e")
        self.errors_text = tk.Text(f, height=8, wrap="word", state="disabled")
        self.errors_text.pack(fill="both", expand=True, pady=(4, 12))

        self.unpair_button = ttk.Button(f, text=t(self.locale, "status.unpair"), command=self._on_unpair)
        self.unpair_button.pack()

    def _show_pairing(self) -> None:
        self.status_frame.pack_forget()
        self.pairing_frame.pack(fill="both", expand=True)
        self.code_entry.focus_set()

    def _show_status(self) -> None:
        self.pairing_frame.pack_forget()
        self.status_frame.pack(fill="both", expand=True)
        self._refresh_status()
        self.root.after(STATUS_POLL_MS, self._poll_status)

    def _poll_status(self) -> None:
        if str(self.status_frame.winfo_manager()):
            self._refresh_status()
            self.root.after(STATUS_POLL_MS, self._poll_status)

    def _refresh_status(self) -> None:
        online = self.uploader.online if self.uploader else True
        self.connection_label.configure(
            text=t(self.locale, "status.connected" if online else "status.offline"),
            foreground="#1a7f37" if online else "#b45309",
        )
        self.folder_label.configure(
            text=f"{t(self.locale, 'status.folder_label')}: {self.settings.folder or '-'}"
        )

        counts = self.queue.counts()
        self.uploaded_label.configure(text=f"{t(self.locale, 'status.uploaded')}: {counts['done']}")
        pending = counts["pending"] + counts["uploading"]
        self.queued_label.configure(text=f"{t(self.locale, 'status.queued')}: {pending}")
        self.failed_label.configure(text=f"{t(self.locale, 'status.failed')}: {counts['failed']}")

        errors = self.queue.recent_errors(limit=20)
        self.errors_text.configure(state="normal")
        self.errors_text.delete("1.0", "end")
        if errors:
            for record in errors:
                filename = Path(record.path).name
                line = t(self.locale, "error.upload_failed", filename=filename)
                self.errors_text.insert("end", f"{line}\n  {record.last_error}\n\n")
        else:
            self.errors_text.insert("end", t(self.locale, "status.no_errors"))
        self.errors_text.configure(state="disabled")

    def _on_catch_up(self) -> None:
        if not self.watcher:
            return
        self.catch_up_button.configure(state="disabled", text=t(self.locale, "status.catch_up_running"))
        threading.Thread(target=self._catch_up_worker, daemon=True).start()

    def _catch_up_worker(self) -> None:
        assert self.watcher is not None
        self.watcher.catch_up_scan()
        self.root.after(
            0,
            lambda: self.catch_up_button.configure(state="normal", text=t(self.locale, "status.catch_up")),
        )

    def _on_unpair(self) -> None:
        if not messagebox.askyesno(t(self.locale, "status.unpair"), t(self.locale, "status.unpair_confirm")):
            return
        self._stop_background_work()
        keychain.clear_token()
        self.token = None
        self.event_id = None
        self._show_pairing()

    # ------------------------------------------------------------------
    # Background work lifecycle
    # ------------------------------------------------------------------
    def _start_background_work(self) -> None:
        if self.settings.folder and Path(self.settings.folder).is_dir():
            self.watcher = FolderWatcher(
                Path(self.settings.folder), self.queue, include_raw=self.settings.include_raw
            )
            self.watcher.start()
        self.uploader = Uploader(self.queue, self.api_client, lambda: self.token, on_auth_error=self._on_auth_error)
        self.uploader.start()

    def _restart_watcher(self) -> None:
        if self.watcher:
            self.watcher.stop()
        if self.settings.folder and Path(self.settings.folder).is_dir():
            self.watcher = FolderWatcher(
                Path(self.settings.folder), self.queue, include_raw=self.settings.include_raw
            )
            self.watcher.start()

    def _stop_background_work(self) -> None:
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        if self.uploader:
            self.uploader.stop()
            self.uploader = None

    def _on_auth_error(self) -> None:
        # Runs on the uploader thread -- hop back to the main thread
        # before touching any tkinter state or the keychain.
        self.root.after(0, self._handle_auth_error)

    def _handle_auth_error(self) -> None:
        self._stop_background_work()
        keychain.clear_token()
        self.token = None
        self.event_id = None
        messagebox.showwarning(
            t(self.locale, "app.title"),
            "This device's connection was revoked. Please pair again."
            if self.locale == "en"
            else "تم إلغاء ربط هذا الجهاز. يرجى إعادة الربط.",
        )
        self._show_pairing()

    # ------------------------------------------------------------------
    # Locale toggle
    # ------------------------------------------------------------------
    def _toggle_locale(self) -> None:
        self.locale = "en" if self.locale == "ar" else "ar"
        self.settings.locale = self.locale
        save_settings(self.settings)
        self._rebuild_texts()

    def _rebuild_texts(self) -> None:
        self.root.title(t(self.locale, "app.title"))
        self.pairing_title.configure(text=t(self.locale, "pair.title"))
        self.pairing_instructions.configure(text=t(self.locale, "pair.instructions"))
        self.pair_button.configure(text=t(self.locale, "pair.submit"))
        self.pairing_locale_button.configure(text=t(self.locale, "locale.toggle"))
        self.status_locale_button.configure(text=t(self.locale, "locale.toggle"))
        self.change_folder_button.configure(text=t(self.locale, "folder.change"))
        self.catch_up_button.configure(text=t(self.locale, "status.catch_up"))
        self.errors_title_label.configure(text=t(self.locale, "status.errors_title"))
        self.unpair_button.configure(text=t(self.locale, "status.unpair"))
        self._refresh_status()

    def _on_close(self) -> None:
        self._stop_background_work()
        self.queue.close()
        self.root.destroy()


def run() -> None:
    root = tk.Tk()
    AgentApp(root)
    root.mainloop()
