# -*- coding: utf-8 -*-
"""Приложение «Радар міста» — іконка в треї Windows.

Аналог menubar.py (macOS/rumps), портований на pystray + tkinter.
Поки застосунок відкрито, радар слухає канали і шле сповіщення.
Консоль не потрібна: запускається подвійним кліком по ярлику
«Радар міста» (pythonw.exe, без вікна консолі).

Колір іконки в треї показує поточний стан:
  🟢 зелений  — працює, тихо
  🔴 червоний — недавно була тривога рівня HIGH
  🟡 жовтий   — оголошена тривога по району
  ⏸ сірий     — пауза
  ⚠️ помаранчевий — помилка (нема мережі, бот не відповідає, не запущено)

Текст стану видно у спливаючій підказці іконки (наведення миші) і в
трьох неактивних пунктах меню.
"""

import asyncio
import ctypes
import os
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

import pystray
from PIL import Image, ImageDraw

import config
import geo
import gui_win
import monitor
import notify

# Сколько минут держать «тревожную» иконку после уведомления
ALERT_ICON_MINUTES = 10

ICON_SIZE = 64

# Кольори станів — ті самі відтінки, що системні кольори macOS
# (systemGreen/systemRed/systemYellow/systemGray/systemOrange), як
# заливка кружка іконки в треї.
STATE_COLORS = {
    "ok": (52, 199, 89),        # 🟢
    "alert": (255, 59, 48),     # 🔴
    "alarm": (255, 204, 0),     # 🟡
    "paused": (142, 142, 147),  # ⏸
    "error": (255, 149, 0),     # ⚠️
}


def make_dot_icon(rgb) -> Image.Image:
    """Кольоровий кружок 64×64 — замінник emoji-заголовка меню-бару macOS."""
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = 4
    draw.ellipse((pad, pad, ICON_SIZE - pad, ICON_SIZE - pad),
                 fill=(rgb[0], rgb[1], rgb[2], 255))
    return img


# Малюємо всі 5 іконок один раз при імпорті — чиста робота Pillow,
# без звернень до ОС, тому безпечно виконувати навіть у final_check.py.
ICONS = {key: make_dot_icon(rgb) for key, rgb in STATE_COLORS.items()}

MUTEX_NAME = "CityRadarTrayApp_SingleInstance_Mutex"


class RadarApp:
    """Аналог menubar.RadarApp: трей-іконка + логіка радара для Windows."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.radar = monitor.Radar(on_alert=self._on_alert)
        self.loop = None
        self.stop_event = None
        self.window = None

        # Пункти меню-статусу — неактивні рядки з динамічним текстом.
        self.item_status_text = "Запуск…"
        self.item_last_text = "Останнє: —"
        self.item_stats_text = "Повідомлень: 0"

        self.icon = pystray.Icon(
            "CityRadar",
            icon=ICONS["ok"],
            title="Радар — запуск…",
            menu=self._build_menu(),
        )

    # --- Меню трея -----------------------------------------------------------
    def _build_menu(self) -> pystray.Menu:
        SEP = pystray.Menu.SEPARATOR
        return pystray.Menu(
            pystray.MenuItem("Відкрити вікно", self.open_window, default=True),
            SEP,
            pystray.MenuItem(lambda item: self.item_status_text, None, enabled=False),
            pystray.MenuItem(lambda item: self.item_last_text, None, enabled=False),
            pystray.MenuItem(lambda item: self.item_stats_text, None, enabled=False),
            SEP,
            pystray.MenuItem(
                lambda item: ("Відновити" if self.radar.paused else "Пауза"),
                self.toggle_pause),
            pystray.MenuItem("Оновити закріплений статус", self.refresh_status),
            pystray.MenuItem("Смарт-звіт у канал", self.send_review),
            pystray.MenuItem(
                lambda item: (f"🔕 Тиша до {self.radar.mute_until:%H:%M}"
                             if self.radar.is_muted() else "Тиша на годину"),
                self.toggle_mute),
            pystray.MenuItem("Звіт за сьогодні в канал", self.send_report),
            pystray.MenuItem("Звіт за вчора в канал", self.send_report_yesterday),
            pystray.MenuItem("Тестове повідомлення", self.send_test),
            SEP,
            pystray.MenuItem("Показати лог", self.open_log),
            pystray.MenuItem("Папка з даними", self.open_config),
            SEP,
            pystray.MenuItem("Вийти", self.quit_app),
        )

    # --- Запуск радара в фоновом потоке -------------------------------------
    def _start_radar(self) -> None:
        def worker():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.stop_event = asyncio.Event()
            try:
                self.loop.run_until_complete(self.radar.run(self.stop_event))
            except SystemExit as e:
                self.item_status_text = str(e)[:60]
                self._push_icon("error")
            except Exception as e:                      # noqa: BLE001
                self.item_status_text = f"Помилка: {type(e).__name__}"
                monitor.log.exception("Радар упав")
                self._push_icon("error")

        threading.Thread(target=worker, daemon=True, name="radar").start()

    def start(self) -> None:
        self._start_radar()
        self.icon.run_detached()
        self.root.after(5000, self._tick)

    def restart_radar(self) -> None:
        """Перезапускает радар — после смены списка каналов.

        Telethon подписывается на каналы при подключении, поэтому
        новый список подхватывается только новым соединением.
        """
        old_loop, old_stop = self.loop, self.stop_event
        if old_loop and old_stop:
            old_loop.call_soon_threadsafe(old_stop.set)

        counts, stats = self.radar.counts, self.radar.stats
        self.radar = monitor.Radar(on_alert=self._on_alert)
        self.radar.counts, self.radar.stats = counts, stats   # счётчики не теряем
        self.item_status_text = "Перезапуск…"
        self._start_radar()

    # --- Реакция на отправленное уведомление --------------------------------
    def _on_alert(self, level: str, headline: str, text: str) -> None:
        # Вызывается из фонового потока — только записываем данные,
        # интерфейс обновит таймер в главном потоке.
        self.item_last_text = f"Останнє: {headline}"

    # --- Періодичне і разове оновлення трея ----------------------------------
    def _push_icon(self, color_key: str) -> None:
        """Миттєво показує колір/підказку — аналог авто-редрава rumps title=."""
        self.icon.icon = ICONS[color_key]
        self.icon.title = self.item_status_text[:120]
        try:
            self.icon.update_menu()
        except Exception:                                # noqa: BLE001
            pass

    def _tick(self) -> None:
        self._refresh_now()
        self.root.after(5000, self._tick)

    def _refresh_now(self) -> None:
        """Повний перерахунок стану — аналог menubar._refresh(self, _timer)."""
        r = self.radar

        if not r.running:
            color_key = "error"
            status_text = "Не працює"
        elif r.paused:
            color_key = "paused"
            status_text = "Пауза — сповіщення не надсилаються"
        else:
            recent = (r.last_alert and r.last_alert[1] == "HIGH" and
                      (datetime.now() - r.last_alert[0]).total_seconds()
                      < ALERT_ICON_MINUTES * 60)
            # 🟡 — объявлена тревога по району, но конкретной угрозы [МІСТО] нет
            color_key = "alert" if recent else ("alarm" if r.alarm else "ok")
            if r.alarm:
                status_text = f"{r.alarm[0]} з {r.alarm[1]:%H:%M}"
            else:
                status_text = (
                    f"Працює · {len(config.CHANNELS)} каналів"
                    + (" · сусіди будять" if config.HIGH_INCLUDES_NEIGHBORS
                       else ""))

        if r.last_alert:
            when, _level, headline = r.last_alert
            self.item_last_text = f"Останнє: {headline} ({when.strftime('%H:%M')})"

        self.item_status_text = status_text
        self.icon.icon = ICONS[color_key]
        self.icon.title = status_text[:120]

        s = r.stats
        self.item_stats_text = (f"Переглянуто {s['seen']} · надіслано {s['sent']}"
                                f" · дублів {s['dupes']}"
                                + (f" · помилок {s['errors']}" if s["errors"] else ""))

        try:
            self.icon.update_menu()
        except Exception:                                # noqa: BLE001
            pass

        if self.window is not None:
            self.root.after(0, self.window.refresh)

    # --- Пункти меню (і виклики з GUI) ---------------------------------------
    def open_window(self, icon=None, item=None) -> None:
        self.root.after(0, self._open_window_now)

    def _open_window_now(self) -> None:
        if self.window is None:
            self.window = gui_win.RadarWindow(self, self.root)
        self.window.show()

    def run_review(self, _sender=None) -> None:
        """Смарт-перевірка каналів на вимогу з застосунку."""
        if not (self.loop and self.radar.running):
            return

        async def job():
            import config as cfg

            if cfg.SMART_REVIEW:
                self.radar.review = await self.radar._smart_review()
            self.radar._wake_reason = "кнопка"
            if self.radar._status_dirty:
                self.radar._status_dirty.set()

        asyncio.run_coroutine_threadsafe(job(), self.loop)

    def cancel_alarm(self) -> None:
        """Скасувати хибну тривогу, не вимикаючи радар."""
        if not (self.loop and self.radar.running):
            return

        async def job():
            self.radar.mode_message = await self.radar.cancel_alarm(
                "із застосунку")

        asyncio.run_coroutine_threadsafe(job(), self.loop)

    def set_mode(self, online: bool) -> None:
        """Перемикає локально/онлайн. Результат читає gui_win.refresh() з radar.mode_message."""
        if not (self.loop and self.radar.running):
            return

        async def job():
            self.radar.mode_message = await self.radar.set_mode(online)

        asyncio.run_coroutine_threadsafe(job(), self.loop)

    def send_review(self, icon=None, item=None) -> None:
        """Смарт-звіт окремим повідомленням у канал."""
        if self.loop and self.radar.running:
            asyncio.run_coroutine_threadsafe(
                self.radar.send_review_to_channel(), self.loop)

    def refresh_status(self, icon=None, item=None) -> None:
        """Внеплановое обновление закреплённого сообщения."""
        if self.loop and self.radar._status_dirty:
            self.loop.call_soon_threadsafe(self.radar._status_dirty.set)

    def toggle_mute(self, icon=None, item=None) -> None:
        """Тишина на час: сообщения приходят, но без звука."""
        radar = self.radar
        if radar.is_muted():
            radar.mute_until = None
        else:
            radar.mute_until = datetime.now() + timedelta(hours=1)
        self._refresh_now()

    def toggle_pause(self, icon=None, item=None) -> None:
        self.radar.paused = not self.radar.paused
        self._refresh_now()

    def send_report_yesterday(self, icon=None, item=None) -> None:
        self.send_report(icon, item, day="yesterday")

    def send_report(self, icon=None, item=None, *, day: str = "today") -> None:
        """Отправляет в канал отчёт за сутки. Без звука."""

        def worker():
            ok, info = notify.send(self.radar.build_report(day), silent=True)
            self.icon.notify(
                info, f"Радар {geo.main_name()} · "
                     f"{'Звіт надіслано' if ok else 'Помилка'}")

        threading.Thread(target=worker, daemon=True).start()

    def send_test(self, icon=None, item=None) -> None:
        ok, info = notify.send(
            f"🧪 <b>Перевірка зв'язку</b>\nРадар {geo.main_name()} працює, "
            f"канал сповіщень доступний.\n{datetime.now().strftime('%H:%M:%S')}")
        self.icon.notify(
            info, f"Радар {geo.main_name()} · "
                 f"{'Тест надіслано' if ok else 'Помилка'}")

    def open_log(self, icon=None, item=None) -> None:
        try:
            os.startfile(str(monitor.LOG_FILE))
        except OSError:
            pass

    def open_config(self, icon=None, item=None) -> None:
        # На Windows студентам не потрібно правити config.py — відкриваємо
        # просто папку з даними (той самий вміст, що й кнопка в GUI).
        try:
            os.startfile(str(config.BASE_DIR))
        except OSError:
            pass

    def quit_app(self, icon=None, item=None) -> None:
        # Аккуратно гасим радар, чтобы состояние дедупликации сохранилось
        if self.loop and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        self.icon.stop()
        self.root.after(0, self.root.destroy)


def _acquire_single_instance():
    """Іменований mutex — другий запущений екземпляр не заважає першому."""
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    ERROR_ALREADY_EXISTS = 183
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        if mutex:
            kernel32.CloseHandle(mutex)
        return None
    return mutex


def main() -> int:
    mutex = _acquire_single_instance()
    if mutex is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Радар міста",
            "Радар уже працює — іконка біля годинника.")
        root.destroy()
        return 0

    root = tk.Tk()
    root.withdraw()

    app = RadarApp(root)
    app.start()

    try:
        root.mainloop()
    finally:
        if app.loop and app.stop_event:
            try:
                app.loop.call_soon_threadsafe(app.stop_event.set)
            except Exception:                            # noqa: BLE001
                pass
        try:
            app.icon.stop()
        except Exception:                                # noqa: BLE001
            pass
        kernel32 = ctypes.windll.kernel32
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
