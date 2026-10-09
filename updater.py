"""No-console local update and rollback window for the portable release."""
from __future__ import annotations

from pathlib import Path
import argparse
import os
import sys
from tkinter import Button, Label, Tk, filedialog, messagebox

from backend.config import ROOT
from backend.release import RecoveryError, ReleaseError
from backend.process_state import is_running, running_marker
from backend.auto_update import AvailableUpdate, UpdateError
from backend.update_install import accept_handoff, install_downloaded, start_manual_runner, wait_for_processes, apply_manual_release, restore_manual_release


def automatic_main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto-root", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--size", required=True, type=int)
    parser.add_argument("--wait-pid", action="append", type=int, default=[])
    parser.add_argument("--ready-file", required=True, type=Path)
    args = parser.parse_args(argv)
    update = AvailableUpdate(args.version, args.package.name, args.size, args.sha256, "")
    # Failure before acknowledgement must not close Tonight or block on a dialog.
    try:
        accept_handoff(args.auto_root, args.package, update, args.ready_file)
    except (OSError, ReleaseError, UpdateError):
        return
    try:
        install_downloaded(args.auto_root, args.package, update, pids=args.wait_pid)
    except RecoveryError as error:
        window = Tk(); window.withdraw()
        messagebox.showerror("Требуется восстановление Tonight", str(error))
        window.destroy()
    except (OSError, ReleaseError, UpdateError):
        window = Tk(); window.withdraw()
        messagebox.showerror("Не удалось обновить Tonight", "Обновление не завершено. Откройте Tonight и повторите; ваши данные сохранены.")
        window.destroy()


def _ensure_stopped(root: Path = ROOT) -> bool:
    if is_running(running_marker(root)):
        messagebox.showwarning("Tonight ещё работает", "Сначала остановьте Tonight в его маленьком окне, затем повторите.")
        return False
    return True


def main(root: Path = ROOT) -> None:
    window = Tk()
    window.title("Обновление Tonight")
    window.resizable(False, False)
    window.configure(padx=28, pady=24)
    Label(window, text="Обновить или вернуть прошлую версию", font=("Segoe UI", 11)).pack(pady=(0, 12))

    def update() -> None:
        if not _ensure_stopped(root):
            return
        path = filedialog.askopenfilename(title="Выберите пакет обновления Tonight", filetypes=[("Пакет Tonight", "Tonight-update-*.zip"), ("ZIP", "*.zip")])
        if not path:
            return
        try:
            release = apply_manual_release(root, Path(path))
        except (OSError, ReleaseError, UpdateError) as exc:
            messagebox.showerror("Не удалось обновить", str(exc))
            return
        messagebox.showinfo("Tonight обновлён", f"Готово: версия {release.version}. Ваши данные и настройки сохранены.")

    def rollback() -> None:
        if not _ensure_stopped(root):
            return
        if not messagebox.askyesno("Вернуть прошлую версию", "Вернуть прежние файлы Tonight? Ваши данные и настройки останутся на месте."):
            return
        try:
            restore_manual_release(root)
        except (OSError, ReleaseError, UpdateError) as exc:
            messagebox.showerror("Не удалось вернуть версию", str(exc))
            return
        messagebox.showinfo("Готово", "Прежняя версия Tonight возвращена. Данные сохранены.")

    Button(window, text="Обновить из файла…", command=update, width=28).pack(pady=3)
    Button(window, text="Вернуть прошлую версию", command=rollback, width=28).pack(pady=3)
    Button(window, text="Закрыть", command=window.destroy, width=28).pack(pady=(10, 0))
    window.mainloop()


if __name__ == "__main__":
    if "--auto-root" in sys.argv[1:]:
        automatic_main(sys.argv[1:])
    elif "--manual-root" in sys.argv[1:]:
        parser = argparse.ArgumentParser()
        parser.add_argument("--manual-root", required=True, type=Path)
        parser.add_argument("--wait-pid", action="append", type=int, default=[])
        args = parser.parse_args()
        wait_for_processes(args.wait_pid)
        main(args.manual_root.resolve())
    elif getattr(sys, "frozen", False):
        # Windows locks a running executable. The updater must be replaceable too.
        start_manual_runner(ROOT, pids=[os.getpid(), os.getppid()])
    else:
        main()
