"""No-console local update and rollback window for the portable release."""
from __future__ import annotations

from pathlib import Path
from tkinter import Button, Label, Tk, filedialog, messagebox

from backend.config import ROOT
from backend.release import ReleaseError, apply_release, rollback_previous
from launcher import is_running, running_marker


def _ensure_stopped() -> bool:
    if is_running(running_marker(ROOT)):
        messagebox.showwarning("Tonight ещё работает", "Сначала остановьте Tonight в его маленьком окне, затем повторите.")
        return False
    return True


def main() -> None:
    window = Tk()
    window.title("Обновление Tonight")
    window.resizable(False, False)
    window.configure(padx=28, pady=24)
    Label(window, text="Обновить или вернуть прошлую версию", font=("Segoe UI", 11)).pack(pady=(0, 12))

    def update() -> None:
        if not _ensure_stopped():
            return
        path = filedialog.askopenfilename(title="Выберите пакет обновления Tonight", filetypes=[("Пакет Tonight", "Tonight-update-*.zip"), ("ZIP", "*.zip")])
        if not path:
            return
        try:
            release = apply_release(ROOT, Path(path))
        except (OSError, ReleaseError) as exc:
            messagebox.showerror("Не удалось обновить", str(exc))
            return
        messagebox.showinfo("Tonight обновлён", f"Готово: версия {release.version}. Ваши данные и настройки сохранены.")

    def rollback() -> None:
        if not _ensure_stopped():
            return
        if not messagebox.askyesno("Вернуть прошлую версию", "Вернуть прежние файлы Tonight? Ваши данные и настройки останутся на месте."):
            return
        try:
            rollback_previous(ROOT)
        except (OSError, ReleaseError) as exc:
            messagebox.showerror("Не удалось вернуть версию", str(exc))
            return
        messagebox.showinfo("Готово", "Прежняя версия Tonight возвращена. Данные сохранены.")

    Button(window, text="Обновить из файла…", command=update, width=28).pack(pady=3)
    Button(window, text="Вернуть прошлую версию", command=rollback, width=28).pack(pady=3)
    Button(window, text="Закрыть", command=window.destroy, width=28).pack(pady=(10, 0))
    window.mainloop()


if __name__ == "__main__":
    main()
