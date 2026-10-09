"""Small visible controller for the no-console Windows build."""
from __future__ import annotations

import queue
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import Button, Label, Tk

import launcher
from backend.config import ROOT


def main() -> None:
    window = Tk()
    # Publish the child PID even if startup hangs before the server is ready.
    launcher.write_running_marker(launcher.running_marker(ROOT))
    window.title("Tonight")
    window.resizable(False, False)
    window.configure(padx=28, pady=24)
    status = Label(window, text="Готовим Tonight…", font=("Segoe UI", 11))
    status.pack(pady=(0, 14))
    events: queue.Queue[BaseException | None] = queue.Queue()

    def run_server() -> None:
        try:
            launcher.main()
        except BaseException as exc:  # surfaced in the small visible window
            log = ROOT / "data" / "logs" / "startup-error.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc(), encoding="utf-8")
            events.put(exc)
        else:
            events.put(None)

    worker = threading.Thread(target=run_server, name="Tonight server", daemon=True)
    worker.start()

    def open_tonight() -> None:
        url = launcher.local_url()
        if url:
            webbrowser.open(url)

    def close() -> None:
        launcher.stop()
        status.configure(text="Останавливаем Tonight…")
        def wait_stopped() -> None:
            if worker.is_alive():
                window.after(100, wait_stopped)
            else:
                window.destroy()
        wait_stopped()

    Button(window, text="Открыть Tonight", command=open_tonight, width=22).pack(pady=3)
    Button(window, text="Остановить Tonight", command=close, width=22).pack(pady=3)
    window.protocol("WM_DELETE_WINDOW", close)

    def refresh() -> None:
        try:
            event = events.get_nowait()
        except queue.Empty:
            if launcher.local_url():
                status.configure(text="Tonight работает в браузере")
            window.after(300, refresh)
            return
        if event is None:
            if launcher.updates.status()["phase"] == "installing":
                window.destroy()
                return
            status.configure(text="Tonight остановлен")
        else:
            status.configure(text="Не удалось запустить Tonight")
        window.after(300, refresh)

    refresh()
    window.mainloop()


if __name__ == "__main__":
    main()
