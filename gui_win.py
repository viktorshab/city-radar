# -*- coding: utf-8 -*-
"""Окно приложения «Радар міста» — версія Windows (tkinter/ttk).

Портовано 1:1 з gui.py (macOS/AppKit): та ж карточка стану, ті самі
кнопки дій і налаштування на трьох вкладках, ті самі підказки «?».
Змінено лише шар віджетів (AppKit -> tkinter/ttk) — логіка читання
й збереження налаштувань перенесена без змін.

Показуються тільки ті налаштування, які дійсно працюють.
"""

import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import backup
import config
import geo
import settings
import status as status_mod

# --- Кольори (наближені до системних кольорів macOS, підібрані для
#     читабельності саме як КОЛІР ТЕКСТУ на світлому тлі) ------------------
COLOR_GREEN = "#1B8A3D"
COLOR_RED = "#CC2B2B"
COLOR_YELLOW = "#B8860B"
COLOR_GRAY = "#8E8E93"
COLOR_ORANGE = "#C56A00"
COLOR_SECONDARY = "#6E6E73"
COLOR_TERTIARY = "#AEAEB2"

CARD_HELP_WRAP = 520


def _set_entry(entry: tk.Entry, value) -> None:
    entry.delete(0, "end")
    entry.insert(0, "" if value is None else str(value))


def _set_text(widget: tk.Text, value) -> None:
    widget.delete("1.0", "end")
    widget.insert("1.0", value or "")


def _get_text(widget: tk.Text) -> str:
    return widget.get("1.0", "end-1c")


class ToolTip:
    """Спливаюча підказка при наведенні — аналог NSButton.setToolTip_."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event=None):
        if self.tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        try:
            self.tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(self.tip, text=self.text, justify="left", wraplength=380,
                          background="#ffffe0", relief="solid", borderwidth=1,
                          font=("Segoe UI", 9), padx=6, pady=4)
        label.pack()

    def _hide(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class RadarWindow:
    """Головне вікно застосунку."""

    def __init__(self, app, root: tk.Tk):
        self.app = app
        self.root = root
        self.help_keys = []          # ключ у settings.HELP на кожну кнопку «?»
        self.channel_fields = []
        self.city_fields = []
        self.city_switches = []
        self.report_open = False
        self.window = None
        self._build()

    # ======================================================================
    #  Построение
    # ======================================================================
    def _build(self) -> None:
        self.window = tk.Toplevel(self.root)
        self.window.title(f"Радар {geo.main_name()} {config.VERSION}")
        self.window.minsize(560, 640)
        self.window.geometry("640x800")
        try:
            self.window.iconbitmap(str(config.BASE_DIR / "CityRadar.ico"))
        except tk.TclError:
            pass                      # немає CityRadar.ico поряд — не критично
        self.window.protocol("WM_DELETE_WINDOW", self.window.withdraw)

        container = ttk.Frame(self.window, padding=14)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        self._build_card(container)
        self._build_actions(container)
        self._build_mode_row(container)
        self._build_tabs(container)
        self._build_footer(container)

        self._load_settings()
        # Ховаємо одразу після побудови: вікно з'являється лише через show().
        self.window.withdraw()

    # --- Прокручувана вкладка -------------------------------------------------
    def _make_scroll_frame(self, parent):
        outer = ttk.Frame(parent)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        vscroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(12, 10))

        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vscroll.set)

        def _sync_scrollregion(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        inner.bind("<Configure>", _sync_scrollregion)
        canvas.bind("<Configure>", _sync_width)
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        return outer, inner

    def _make_text_area(self, parent, height=3):
        frame = ttk.Frame(parent)
        text = tk.Text(frame, height=height, wrap="word", undo=False,
                        font=("Consolas", 9))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        return frame, text

    # --- Карточка состояния -------------------------------------------------
    def _build_card(self, container) -> None:
        card = ttk.Frame(container, relief="groove", borderwidth=2, padding=12)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        card.columnconfigure(0, weight=1)
        self.card = card

        self.lbl_state = ttk.Label(card, text="Запуск…", font=("Segoe UI", 16, "bold"))
        self.lbl_state.grid(row=0, column=0, sticky="w")

        self.lbl_sub = ttk.Label(card, text="", foreground=COLOR_SECONDARY)
        self.lbl_sub.grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.lbl_last = ttk.Label(card, text="Останнє: —")
        self.lbl_last.grid(row=2, column=0, sticky="w", pady=(6, 0))

        toggle_row = ttk.Frame(card)
        toggle_row.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.btn_toggle_report = ttk.Button(toggle_row, text="▸ Звіт за сьогодні",
                                            command=self.toggleReport_)
        self.btn_toggle_report.pack(side="left")
        self.btn_report_refresh = ttk.Button(toggle_row, text="Оновити",
                                             command=self.refreshReport_)
        # Кнопка «Оновити» звіту прихована, поки звіт не розкрито — не пакуємо.

        self.lbl_counts = ttk.Label(card, text="", justify="left", anchor="w",
                                    wraplength=CARD_HELP_WRAP)
        self.lbl_counts.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.lbl_counts.grid_remove()
        self.report_open = False

    # --- Верхняя панель кнопок ----------------------------------------------
    def _build_actions(self, container) -> None:
        """Основные действия — всегда на виду, над вкладками.

        У каждой кнопки всплывающая подсказка: без неё по одному слову
        не всегда понятно, что произойдёт.
        """
        actions = ttk.Frame(container)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for col in range(3):
            actions.columnconfigure(col, weight=1)

        specs = (
            ("Зняти тривогу", self.cancelAlarm_,
             "ЗНЯТИ ТРИВОГУ ВРУЧНУ.\n\n"
             "Прибирає активну ціль і зупиняє гучні повтори, але радар "
             "продовжує працювати.\n\n"
             "Натискайте, коли ціль уже збили, вона пішла чи вибухнула, "
             "а радар цього не побачив, — або коли він помилився. Це "
             "не означає, що сповіщення було хибним.\n\n"
             "Ще 15 хвилин повідомлення про те саме місце йдуть без "
             "звуку. Якщо загроза зросте (ракета, балістика, бандероль, "
             "5+ цілей) — звук повернеться.\n\n"
             "У канал піде коротке повідомлення, що тривогу знято вручну."),
            ("Пауза сповіщень", self.pause_,
             "Тимчасово припинити сповіщення. Радар продовжує слухати "
             "канали, але нічого не надсилає."),
            ("Тиша на годину", self.mute_,
             "Тиша на годину: повідомлення приходять, але без звуку. "
             "Корисно, коли обстріл триває довго, а ви вже в укритті. "
             "Діє й на екстрені повтори."),
            ("Перевірка зв'язку", self.test_,
             "Надіслати в канал перевірочне повідомлення — переконатися, "
             "що зв'язок з ботом працює."),
            ("Оновити закріп", self.refreshStatus_,
             "Оновити закріплене повідомлення в каналі просто зараз, "
             "не чекаючи розкладу."),
            ("Звіт сьогодні", self.report_,
             "Надіслати в канал звіт від 00:00 до цього моменту: загрози "
             "з розбивкою за типами, прильоти, тривоги, світло."),
            ("Звіт за вчора", self.reportPrev_,
             "Надіслати в канал звіт за минулу добу."),
            ("Смарт-звіт у канал", self.sendReview_,
             "Перевірити канали і надіслати мікрозвіт окремим "
             "повідомленням у канал, без звуку."),
            ("Перезапустити радар", self.reload_,
             "Скинути закріплене повідомлення і перезапустити радар. "
             "Створюється нове закріплене, стан тривоги перечитується "
             "з історії каналів."),
            ("Смарт-Оновити", self.toggleSmartButton_,
             "Перемикач для кнопки «Оновити» під закріпленим у каналі.\n\n"
             "Підсвічено (увімкнено) — кнопка «Оновити» переглядає останні "
             "повідомлення каналів і сама вирішує, чи знята ціль.\n\n"
             "Тьмяно (вимкнено) — кнопка просто перемальовує час, як "
             "стара версія, без жодного аналізу."),
        )
        for i, (title, action, tip) in enumerate(specs):
            btn = ttk.Button(actions, text=title, command=action)
            row, col = divmod(i, 3)
            btn.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
            ToolTip(btn, tip)
            if title.startswith("Пауза"):
                self.btn_pause = btn
            elif title.startswith("Зняти"):
                self.btn_cancel = btn
            elif title.startswith("Тиша"):
                self.btn_mute = btn
            elif title.startswith("Смарт-Оновити"):
                self.btn_smart_button = btn

    # --- Тумблер «Локально / Онлайн» ----------------------------------------
    def _build_mode_row(self, container) -> None:
        tip = ("Де зараз працює радар. «Локально» — на цьому пристрої. "
              "«Онлайн» — на сервері 24/7, цей пристрій можна вимкнути. "
              "Перемикання одразу застосовується з обох боків, якщо "
              "хмара налаштована (див. «Додатково»).")

        row = ttk.Frame(container)
        row.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(2, weight=1)

        self.lbl_local = ttk.Label(row, text="Локально", font=("Segoe UI", 11, "bold"),
                                   anchor="e")
        self.lbl_local.grid(row=0, column=0, sticky="e", padx=(0, 10))
        ToolTip(self.lbl_local, tip)

        self.var_mode = tk.BooleanVar(value=False)
        self.mode_switch = ttk.Checkbutton(row, variable=self.var_mode,
                                           command=self.toggleMode_)
        self.mode_switch.grid(row=0, column=1)
        ToolTip(self.mode_switch, tip)

        self.lbl_online = ttk.Label(row, text="Онлайн", font=("Segoe UI", 11, "bold"),
                                    anchor="w")
        self.lbl_online.grid(row=0, column=2, sticky="w", padx=(10, 0))
        ToolTip(self.lbl_online, tip)

        self.lbl_mode_status = ttk.Label(row, text="", foreground=COLOR_SECONDARY)
        self.lbl_mode_status.grid(row=1, column=0, columnspan=3, pady=(4, 0))

    # --- Вкладки --------------------------------------------------------------
    def _build_tabs(self, container) -> None:
        self.tabs = ttk.Notebook(container)
        self.tabs.grid(row=3, column=0, sticky="nsew", pady=(4, 0))

        outer1, inner1 = self._make_scroll_frame(self.tabs)
        self._fill_alerts(inner1)
        self.tabs.add(outer1, text="Сповіщення")

        outer2, inner2 = self._make_scroll_frame(self.tabs)
        self._fill_channels(inner2)
        self.tabs.add(outer2, text="Канали і міста")

        outer3, inner3 = self._make_scroll_frame(self.tabs)
        self._fill_extra(inner3)
        self.tabs.add(outer3, text="Додатково")

    # --- Допоміжні будівельні блоки -----------------------------------------
    def _add_help(self, row, key: str) -> None:
        self.help_keys.append(key)
        btn = ttk.Button(row, text="?", width=2,
                         command=lambda k=key: self.showHelp_(k))
        btn.pack(side="right")

    def _checkbox_row(self, parent, text, help_key, prefix=""):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=1)
        var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text=prefix + text, variable=var,
                        command=self.touched_).pack(side="left", anchor="w")
        self._add_help(row, help_key)
        return var

    def _numeric_row(self, parent, label_text, help_key, width=6, unit="хв"):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text=label_text, width=20).pack(side="left")
        entry = ttk.Entry(row, width=width)
        entry.pack(side="left")
        ttk.Label(row, text=unit, foreground=COLOR_SECONDARY).pack(side="left",
                                                                    padx=(4, 0))
        self._add_help(row, help_key)
        return entry

    # --- Вкладка «Сповіщення» -------------------------------------------------
    def _fill_alerts(self, v) -> None:
        ttk.Label(v, text="Звичайні налаштування",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        plain = [
            ("cb_neighbors", "Будити на підльоті через сусідні села",
             "high_includes_neighbors"),
            ("cb_medium", "Надсилати повідомлення рівня MEDIUM", "send_medium"),
            ("cb_low", "Надсилати відбій (LOW)", "send_low"),
            ("cb_info", "Надсилати «звуки наші», роботу ППО (INFO)", "send_info"),
            ("cb_critical", "Особлива небезпека: 3 гучні повтори",
             "critical_enabled"),
            ("cb_civil", "Світло, вода, газ, хімія, ДРГ (без звуку)", "send_civil"),
            ("cb_near", "Цілі на найближчі села (тихо)", "send_near"),
            ("cb_dup_notice", "Позначка можливого дубляжу цілі з іншого каналу",
             "dup_notice_enabled"),
            ("cb_smart_read", "Глибокий розбір повідомлення (тип — з потрібного рядка)",
             "smart_read"),
            ("cb_report_clear", "Знімати ціль за свіжими зведеннями по області",
             "report_clear"),
            ("cb_raid_calm", "Наліт: звук лише на початку й при зростанні загрози",
             "raid_calm"),
        ]
        for attr, title, key in plain:
            setattr(self, attr, self._checkbox_row(v, title, key))

        row = ttk.Frame(v)
        row.pack(fill="x", pady=1)
        self.cb_clear = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Повідомляти, коли загроза минула",
                        variable=self.cb_clear, command=self.touched_).pack(side="left")
        ttk.Label(row, text="через").pack(side="left", padx=(6, 2))
        self.f_clear = ttk.Entry(row, width=6)
        self.f_clear.pack(side="left")
        ttk.Label(row, text="хв", foreground=COLOR_SECONDARY).pack(side="left",
                                                                    padx=(2, 0))
        self._add_help(row, "clear_threat")

        row = ttk.Frame(v)
        row.pack(fill="x", pady=1)
        self.cb_quiet = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Тихі години — без звуку з",
                        variable=self.cb_quiet, command=self.touched_).pack(side="left")
        self.f_quiet_from = ttk.Entry(row, width=5)
        self.f_quiet_from.pack(side="left", padx=(4, 2))
        ttk.Label(row, text="до").pack(side="left")
        self.f_quiet_to = ttk.Entry(row, width=5)
        self.f_quiet_to.pack(side="left", padx=(4, 2))
        ttk.Label(row, text="год", foreground=COLOR_SECONDARY).pack(side="left")
        self._add_help(row, "quiet_hours")

        # --- Смарт-режим: вмикається одним прапорцем або поштучно ---------
        row = ttk.Frame(v)
        row.pack(fill="x", pady=(14, 2))
        ttk.Label(row, text="Смарт-режим", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.cb_smart_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="усі разом", variable=self.cb_smart_all,
                        command=self.smartAll_).pack(side="left", padx=(10, 0))

        ttk.Label(v, text="Перевірки, що прибирають хибні тривоги. Вимикайте, "
                          "якщо котрась заважає.", foreground=COLOR_SECONDARY,
                 wraplength=CARD_HELP_WRAP, justify="left").pack(fill="x", pady=(0, 6))

        smart = [
            ("cb_replace", "Власні типи ЗАМІНЮЮТЬ вбудовані", "types_replace"),
            ("cb_planned", "Розмінування — не вважати прильотом", "filter_planned"),
            ("cb_conf", "Невпевнені висновки — без звуку", "filter_confidence"),
            ("cb_votes", "Відбій лише після двох каналів", "filter_votes"),
            ("cb_context", "Враховувати відповіді каналів", "filter_context"),
            ("cb_review", "Кнопка «Оновити» переглядає канали", "smart_review"),
            ("cb_explain", "Шукати ймовірне джерело вибуху", "smart_explain"),
            ("cb_series", "Перевіряти канали перед серією загроз",
             "smart_before_series"),
        ]
        for attr, title, key in smart:
            setattr(self, attr, self._checkbox_row(v, title, key, prefix="      "))

    # --- Вкладка «Канали і міста» ---------------------------------------------
    def _fill_channels(self, v) -> None:
        row = ttk.Frame(v)
        row.pack(fill="x")
        ttk.Label(row, text="Канали, які слухає радар. По одному в рядок, "
                            "без «@». Порожні рядки ігноруються.",
                 foreground=COLOR_SECONDARY, wraplength=CARD_HELP_WRAP,
                 justify="left").pack(side="left", fill="x", expand=True)
        self._add_help(row, "channels")

        self.channel_fields = []
        for i in range(10):
            crow = ttk.Frame(v)
            crow.pack(fill="x", pady=1)
            ttk.Label(crow, text=f"{i + 1}.", width=3,
                     foreground=COLOR_TERTIARY).pack(side="left")
            entry = ttk.Entry(crow)
            entry.pack(side="left", fill="x", expand=True)
            self.channel_fields.append(entry)

        row = ttk.Frame(v)
        row.pack(fill="x", pady=(14, 0))
        ttk.Label(row, text="Міста", font=("Segoe UI", 10, "bold")).pack(side="left")
        self._add_help(row, "cities")
        ttk.Label(v, text="Назва міста і всі його написання через кому — "
                          "усіма мовами й відмінками.", foreground=COLOR_SECONDARY,
                 wraplength=CARD_HELP_WRAP, justify="left").pack(fill="x", pady=(2, 8))

        self.city_fields = []
        self.city_switches = []
        for idx, title in enumerate(("Головне", "Додаткове 1", "Додаткове 2")):
            crow = ttk.Frame(v)
            crow.pack(fill="x", pady=(4, 0))
            if idx == 0:
                ttk.Label(crow, text=title, width=12).pack(side="left")
            else:
                var = tk.BooleanVar(value=False)
                ttk.Checkbutton(crow, text=title, variable=var,
                                command=self.touched_).pack(side="left")
                self.city_switches.append(var)
            name_entry = ttk.Entry(crow)
            name_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))

            area_frame, area = self._make_text_area(v, height=3)
            area_frame.pack(fill="x", pady=(2, 0))
            self.city_fields.append((name_entry, area))

        ttk.Label(v, text="Головне місто йде і в закріплене, і в пости. "
                          "Додаткові — лише пости.", foreground=COLOR_SECONDARY,
                 wraplength=CARD_HELP_WRAP, justify="left").pack(fill="x", pady=(6, 10))

        row = ttk.Frame(v)
        row.pack(fill="x")
        ttk.Label(row, text="Район", width=12).pack(side="left")
        self.f_district_name = ttk.Entry(row)
        self.f_district_name.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._add_help(row, "district")

        area_frame, self.f_district_var = self._make_text_area(v, height=2)
        area_frame.pack(fill="x", pady=(4, 8))

        ttk.Label(v, text="Перш ніж міняти місто — змініть канали: нинішні "
                          "мають писати про ваш регіон.", foreground="#B8860B",
                 wraplength=CARD_HELP_WRAP, justify="left").pack(fill="x")

    # --- Вкладка «Додатково» ---------------------------------------------------
    def _fill_extra(self, v) -> None:
        ttk.Label(v, text="Закріплене повідомлення",
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))

        self.f_status = self._numeric_row(v, "Оновлювати кожні", "status_update_min")
        self.f_alarm = self._numeric_row(v, "Тримати «Є загроза»",
                                         "status_alarm_window_min")

        self.cb_oblast = self._checkbox_row(
            v, "Враховувати тривогу по району / області", "track_oblast_alarm")
        self.cb_announce = self._checkbox_row(
            v, "Тривогу і відбій — окремим повідомленням", "announce_alarm")
        self.cb_button = self._checkbox_row(
            v, "Кнопка «Оновити» під закріпленим", "status_refresh_button")

        ttk.Label(v, text="Службове", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(12, 6))

        self.f_dedup = self._numeric_row(v, "Склейка дублів", "dedup_window_min")

        row = ttk.Frame(v)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text="Режим роботи", width=20).pack(side="left")
        self._add_help(row, "role")

        btn_row = ttk.Frame(v)
        btn_row.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_row, text="Показати лог", command=self.log_).pack(side="left")
        ttk.Button(btn_row, text="Папка з даними", command=self.folder_).pack(
            side="left", padx=(8, 0))

        ttk.Label(v, text="Резервна копія — щоб не переносити файли вручну "
                          "при перевстановленні:", foreground=COLOR_SECONDARY,
                 wraplength=CARD_HELP_WRAP, justify="left").pack(fill="x", pady=(12, 4))
        btn_row = ttk.Frame(v)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Зберегти копію…", command=self.saveBackup_).pack(
            side="left")
        ttk.Button(btn_row, text="Відновити з копії…", command=self.loadBackup_).pack(
            side="left", padx=(8, 0))

        ttk.Label(v, text="Онлайн-екземпляр (сервер):", foreground=COLOR_SECONDARY,
                 wraplength=CARD_HELP_WRAP, justify="left").pack(fill="x", pady=(12, 4))
        cloud_row = ttk.Frame(v)
        cloud_row.pack(fill="x")
        ttk.Button(cloud_row, text="🔁 Перезапустити онлайн",
                  command=self.restartCloud_).pack(side="left")
        self.lbl_cloud_status = ttk.Label(cloud_row, text="", foreground=COLOR_SECONDARY)
        self.lbl_cloud_status.pack(side="left", padx=(8, 0))

        sync_tip = ("Надсилає ВСІ налаштування з цього застосунку (канали, "
                   "міста, фільтри, пороги тощо — все, крім ролі, власника "
                   "бота й токена каналу) на сервер і перезапускає його, "
                   "щоб вони одразу застосувались.\n\n"
                   "Працює лише в один бік: з комп'ютера на хмару. Якщо "
                   "після цього щось перемкнути через бота (наприклад, "
                   "паузу чи розумні фільтри), наступна синхронізація зі "
                   "старими налаштуваннями з комп'ютера може це скасувати — "
                   "тому тисніть цю кнопку саме тоді, коли щось змінили тут, "
                   "у застосунку.")
        sync_row = ttk.Frame(v)
        sync_row.pack(fill="x", pady=(8, 0))
        btn_sync = ttk.Button(sync_row, text="🔄 Синхронізувати налаштування",
                              command=self.syncSettings_)
        btn_sync.pack(side="left")
        ToolTip(btn_sync, sync_tip)
        self.lbl_sync_status = ttk.Label(sync_row, text="", foreground=COLOR_SECONDARY)
        self.lbl_sync_status.pack(side="left", padx=(8, 0))
        ToolTip(self.lbl_sync_status, sync_tip)

        row = ttk.Frame(v)
        row.pack(fill="x", pady=(14, 0))
        ttk.Label(row, text="Власні типи загроз",
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self._add_help(row, "types_custom")
        ttk.Label(v, text="Один тип у рядку: «Назва: корінь, корінь». "
                          "Наприклад — Зевс: зевс, zeus", foreground=COLOR_SECONDARY,
                 wraplength=CARD_HELP_WRAP, justify="left").pack(fill="x", pady=(2, 6))

        for caption, attr in (("Гучні — будять", "f_types_loud"),
                              ("Тихі — без звуку", "f_types_silent"),
                              ("Лише в закріплене", "f_types_pinned")):
            ttk.Label(v, text=caption).pack(anchor="w")
            area_frame, area = self._make_text_area(v, height=3)
            area_frame.pack(fill="x", pady=(2, 8))
            setattr(self, attr, area)

        row = ttk.Frame(v)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="Канал сповіщень",
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        self._add_help(row, "target_chat")
        ttk.Label(v, text="Порожньо — брати з .env. Заповніть, щоб "
                          "перенаправити радар в інший канал.",
                 foreground=COLOR_SECONDARY, wraplength=CARD_HELP_WRAP,
                 justify="left").pack(fill="x", pady=(2, 6))

        row = ttk.Frame(v)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text="ID каналу", width=12).pack(side="left")
        self.f_chat_id = ttk.Entry(row)
        self.f_chat_id.pack(side="left", fill="x", expand=True)

        row = ttk.Frame(v)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text="Токен бота", width=12).pack(side="left")
        self.f_bot_token = ttk.Entry(row)
        self.f_bot_token.pack(side="left", fill="x", expand=True)

        ttk.Label(v, text="Змінюйте токен лише якщо втрачено самого бота. "
                          "Після зміни каналу закріплене створюється заново.",
                 foreground="#B8860B", wraplength=CARD_HELP_WRAP,
                 justify="left").pack(fill="x", pady=(8, 0))

    # --- Низ окна --------------------------------------------------------------
    def _build_footer(self, container) -> None:
        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.btn_save = ttk.Button(footer, text="Зберегти", command=self.save_)
        self.btn_save.pack(side="left")
        self.lbl_saved = ttk.Label(footer, text="", foreground=COLOR_SECONDARY)
        self.lbl_saved.pack(side="left", padx=(12, 0))

    # ======================================================================
    #  Настройки
    # ======================================================================
    def _load_settings(self) -> None:
        s = settings.load()
        import railway_ctl

        self.lbl_cloud_status.configure(
            text="Готово до керування" if railway_ctl.available()
            else "Не налаштовано (див. .env)")
        self.cb_neighbors.set(bool(s["high_includes_neighbors"]))
        self.cb_medium.set(bool(s["send_medium"]))
        self.cb_low.set(bool(s["send_low"]))
        self.cb_info.set(bool(s["send_info"]))
        self.cb_quiet.set(bool(s["quiet_hours_enabled"]))
        self.cb_oblast.set(bool(s["track_oblast_alarm"]))
        self.cb_announce.set(bool(s["announce_alarm"]))
        self.cb_button.set(bool(s["status_refresh_button"]))
        self.cb_clear.set(bool(s["clear_threat"]))
        self.cb_critical.set(bool(s["critical_enabled"]))
        self.cb_civil.set(bool(s["send_civil"]))
        self.cb_near.set(bool(s["send_near"]))
        self.cb_dup_notice.set(bool(s.get("dup_notice_enabled", True)))
        self.cb_smart_read.set(bool(s.get("smart_read", True)))
        self.cb_report_clear.set(bool(s.get("report_clear", True)))
        self.cb_raid_calm.set(bool(s.get("raid_calm", True)))
        self.cb_replace.set(bool(s.get("types_replace")))
        self.cb_planned.set(bool(s["filter_planned"]))
        self.cb_conf.set(bool(s["filter_confidence"]))
        self.cb_votes.set(bool(s["filter_votes"]))
        self.cb_context.set(bool(s["filter_context"]))
        self.cb_review.set(bool(s.get("smart_review")))
        self.cb_explain.set(bool(s.get("smart_explain")))
        self.cb_series.set(bool(s.get("smart_before_series")))
        self.cb_smart_all.set(
            all(s[k] for k in ("filter_planned", "filter_confidence",
                               "filter_votes", "filter_context",
                               "smart_review", "smart_explain",
                               "smart_before_series")))
        _set_entry(self.f_clear, s["clear_after_min"])
        _set_entry(self.f_quiet_from, s["quiet_from"])
        _set_entry(self.f_quiet_to, s["quiet_to"])
        _set_entry(self.f_status, s["status_update_min"])
        _set_entry(self.f_alarm, s["status_alarm_window_min"])
        _set_entry(self.f_dedup, s["dedup_window_min"])
        for i, f in enumerate(self.channel_fields):
            _set_entry(f, s["channels"][i] if i < len(s["channels"]) else "")

        keys = (("city_main_name", "city_main_variants"),
                ("city_2_name", "city_2_variants"),
                ("city_3_name", "city_3_variants"))
        for (name_f, var_f), (kn, kv) in zip(self.city_fields, keys):
            _set_entry(name_f, s.get(kn, ""))
            _set_text(var_f, s.get(kv, ""))
        self.city_switches[0].set(bool(s.get("city_2_on")))
        self.city_switches[1].set(bool(s.get("city_3_on")))
        _set_entry(self.f_district_name, s.get("district_name", ""))
        _set_entry(self.f_chat_id, s.get("target_chat_id", ""))
        _set_entry(self.f_bot_token, s.get("bot_token", ""))
        _set_text(self.f_district_var, s.get("district_variants", ""))
        # Порожні поля заповнюємо вбудованими типами: щоб було видно,
        # що зараз працює, і можна було відредагувати або видалити рядок.
        import threats as _threats

        loud_txt, silent_txt = _threats.builtin_as_text()
        _set_text(self.f_types_loud, s.get("types_loud") or loud_txt)
        _set_text(self.f_types_silent, s.get("types_silent") or silent_txt)
        _set_text(self.f_types_pinned, s.get("types_pinned", ""))

    def _num(self, entry, fallback, low, high):
        try:
            value = int(entry.get().strip())
        except ValueError:
            return fallback
        return max(low, min(high, value))

    def save_(self) -> None:
        old = settings.load()
        channels = []
        for f in self.channel_fields:
            name = f.get().strip().lstrip("@")
            if name and name not in channels:
                channels.append(name)

        cities = {}
        keys = (("city_main_name", "city_main_variants"),
                ("city_2_name", "city_2_variants"),
                ("city_3_name", "city_3_variants"))
        for (name_f, var_f), (kn, kv) in zip(self.city_fields, keys):
            cities[kn] = name_f.get().strip()
            cities[kv] = _get_text(var_f).strip()
        cities["city_2_on"] = bool(self.city_switches[0].get())
        cities["city_3_on"] = bool(self.city_switches[1].get())
        # Главный город без вариантов написания сломал бы весь фильтр
        if not cities["city_main_variants"]:
            cities["city_main_name"] = old["city_main_name"]
            cities["city_main_variants"] = old["city_main_variants"]

        settings.save({
            **cities,
            "district_name": self.f_district_name.get().strip()
                             or old["district_name"],
            "district_variants": _get_text(self.f_district_var).strip()
                                 or old["district_variants"],
            "types_loud": _get_text(self.f_types_loud).strip(),
            "types_silent": _get_text(self.f_types_silent).strip(),
            "types_pinned": _get_text(self.f_types_pinned).strip(),
            "owner_id": old["owner_id"],
            "target_chat_id": self.f_chat_id.get().strip(),
            "bot_token": self.f_bot_token.get().strip(),
            "role": old["role"],
            "telegram_control": old["telegram_control"],
            "channels": channels or old["channels"],
            "high_includes_neighbors": bool(self.cb_neighbors.get()),
            "send_medium": bool(self.cb_medium.get()),
            "send_low": bool(self.cb_low.get()),
            "send_info": bool(self.cb_info.get()),
            "quiet_hours_enabled": bool(self.cb_quiet.get()),
            "quiet_from": self._num(self.f_quiet_from, old["quiet_from"], 0, 23),
            "quiet_to": self._num(self.f_quiet_to, old["quiet_to"], 0, 23),
            "status_update_min": self._num(self.f_status,
                                           old["status_update_min"], 1, 120),
            "status_alarm_window_min": self._num(
                self.f_alarm, old["status_alarm_window_min"], 5, 240),
            "track_oblast_alarm": bool(self.cb_oblast.get()),
            "announce_alarm": bool(self.cb_announce.get()),
            "status_refresh_button": bool(self.cb_button.get()),
            "clear_threat": bool(self.cb_clear.get()),
            "critical_enabled": bool(self.cb_critical.get()),
            "send_civil": bool(self.cb_civil.get()),
            "send_near": bool(self.cb_near.get()),
            "dup_notice_enabled": bool(self.cb_dup_notice.get()),
            "smart_read": bool(self.cb_smart_read.get()),
            "report_clear": bool(self.cb_report_clear.get()),
            "raid_calm": bool(self.cb_raid_calm.get()),
            "types_replace": bool(self.cb_replace.get()),
            "filter_planned": bool(self.cb_planned.get()),
            "filter_confidence": bool(self.cb_conf.get()),
            "filter_votes": bool(self.cb_votes.get()),
            "filter_context": bool(self.cb_context.get()),
            "smart_review": bool(self.cb_review.get()),
            "smart_explain": bool(self.cb_explain.get()),
            "smart_before_series": bool(self.cb_series.get()),
            "clear_after_min": self._num(self.f_clear, old["clear_after_min"],
                                         3, 180),
            "dedup_window_min": self._num(self.f_dedup,
                                          old["dedup_window_min"], 1, 120),
            "dump_days": old["dump_days"],
        })
        config.reload_settings()
        geo.reload_cities()
        self._load_settings()

        # Канал сменился — старое закреплённое осталось в другом канале,
        # его id больше не годится: создаём новое.
        new_chat = self.f_chat_id.get().strip()
        if new_chat != (old.get("target_chat_id") or ""):
            status_mod.STATE_FILE.unlink(missing_ok=True)
            self.app.restart_radar()
            self.lbl_saved.configure(
                text="Збережено ✓ · канал змінено, радар перезапускається")
            return

        # Список каналов читается при подключении, поэтому радар
        # перезапускается — иначе настройка бы не работала.
        if channels and channels != old["channels"]:
            self.app.restart_radar()
            self.lbl_saved.configure(text="Збережено ✓ · радар перезапускається")
        else:
            self.lbl_saved.configure(text="Збережено ✓")

    def smartAll_(self) -> None:
        """Один прапорець вмикає або вимикає всі смарт-перевірки."""
        state = bool(self.cb_smart_all.get())
        for attr in ("cb_planned", "cb_conf", "cb_votes", "cb_context",
                     "cb_review", "cb_explain", "cb_series"):
            getattr(self, attr).set(state)
        self.lbl_saved.configure(text="Є незбережені зміни")

    def touched_(self) -> None:
        self.lbl_saved.configure(text="Є незбережені зміни")

    # ======================================================================
    #  Действия
    # ======================================================================
    def showHelp_(self, key: str) -> None:
        messagebox.showinfo("Про це налаштування", settings.HELP.get(key, ""),
                            parent=self.window)

    def toggleMode_(self) -> None:
        """Перемикач «Локально / Онлайн» — керує застосунком через app.set_mode."""
        online = bool(self.var_mode.get())
        self.lbl_mode_status.configure(text="Перемикаю…")
        self.app.set_mode(online)

    def _confirm(self, title, message, yes_text, no_text) -> bool:
        """Невеличкий модальний діалог із точним текстом кнопок (як в оригіналі)."""
        dialog = tk.Toplevel(self.window)
        dialog.title(title)
        dialog.transient(self.window)
        dialog.resizable(False, False)

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, text=message, wraplength=380,
                 justify="left").pack(anchor="w", pady=(8, 16))

        result = {"ok": False}

        def on_yes():
            result["ok"] = True
            dialog.destroy()

        def on_no():
            dialog.destroy()

        btns = ttk.Frame(frame)
        btns.pack(anchor="e")
        ttk.Button(btns, text=no_text, command=on_no).pack(side="right")
        ttk.Button(btns, text=yes_text, command=on_yes).pack(side="right", padx=(0, 6))

        dialog.protocol("WM_DELETE_WINDOW", on_no)
        dialog.update_idletasks()
        x = self.window.winfo_rootx() + (self.window.winfo_width()
                                         - dialog.winfo_width()) // 2
        y = self.window.winfo_rooty() + (self.window.winfo_height()
                                         - dialog.winfo_height()) // 2
        dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dialog.grab_set()
        dialog.wait_window()
        return result["ok"]

    def reload_(self) -> None:
        """Сбрасывает закреплённое сообщение и перезапускает радар."""
        ok = self._confirm(
            "Перезапустити радар?",
            "У каналі буде створене нове закріплене повідомлення, "
            "а стан тривоги радар перечитає з історії каналів за 6 годин.\n\n"
            "Старе закріплене залишиться в каналі як звичайний пост.",
            "Перезапустити", "Скасувати")
        if not ok:
            return

        status_mod.STATE_FILE.unlink(missing_ok=True)   # забыть старое
        self.app.restart_radar()
        self.lbl_saved.configure(text="Радар перезапускається…")

    def toggleReport_(self) -> None:
        """Разворачивает и сворачивает отчёт за сегодня."""
        self.report_open = not self.report_open
        if self.report_open:
            self.btn_toggle_report.configure(text="▾ Звіт за сьогодні")
            self.btn_report_refresh.pack(side="left", padx=(6, 0))
            self.lbl_counts.grid()
        else:
            self.btn_toggle_report.configure(text="▸ Звіт за сьогодні")
            self.btn_report_refresh.pack_forget()
            self.lbl_counts.grid_remove()
        self.refresh()

    def refreshReport_(self) -> None:
        self.refresh()

    def mute_(self) -> None:
        self.app.toggle_mute()
        self.refresh()

    def pause_(self) -> None:
        self.app.toggle_pause()
        self.refresh()

    def test_(self) -> None:
        self.app.send_test()

    def cancelAlarm_(self) -> None:
        """Прибирає хибну тривогу, лишаючи радар працювати."""
        self.app.cancel_alarm()
        self.lbl_saved.configure(text="Тривогу знято — радар працює далі")
        self.refresh()

    def toggleSmartButton_(self) -> None:
        """Смарт-режим кнопки «Оновити» під закріпленим у каналі."""
        saved = settings.load()
        saved["smart_review"] = not saved.get("smart_review", True)
        settings.save(saved)
        config.reload_settings()
        self.refresh()

    def refreshStatus_(self) -> None:
        """Смарт-перевірка каналів і оновлення закріпленого."""
        self.app.run_review(None)
        self.report_open = True
        self.btn_toggle_report.configure(text="▾ Звіт за сьогодні")
        self.btn_report_refresh.pack(side="left", padx=(6, 0))
        self.lbl_counts.grid()
        self.lbl_saved.configure(text="Перевіряю канали…")
        self.refresh()
        self.lbl_saved.configure(text="Закріплене оновлюється…")

    def saveBackup_(self) -> None:
        """Складывает секреты и настройки в один файл."""
        path = filedialog.asksaveasfilename(
            parent=self.window, title="Зберегти резервну копію радара",
            initialfile="CityRadar-backup.zip", defaultextension=".zip",
            filetypes=[("ZIP архів", "*.zip")])
        if not path:
            return
        ok, info = backup.create(path)
        self._alert("Резервна копія",
                    (f"Копію збережено. {info}.\n\nУ ній лежать секрети "
                     "й авторизація Telegram — зберігайте її в надійному "
                     "місці й нікому не передавайте.") if ok
                    else f"Не вдалося: {info}")

    def restartCloud_(self) -> None:
        """Перезапускає онлайн-екземпляр — на випадок збою в хмарі."""
        import railway_ctl

        if not railway_ctl.available():
            self.lbl_cloud_status.configure(text="Не налаштовано (див. .env)")
            return

        self.lbl_cloud_status.configure(text="Перезапускаю…")

        def worker():
            ok, info = railway_ctl.restart()
            text = "✅ Перезапущено" if ok else f"⚠️ {info}"
            self.root.after(0, lambda: self.lbl_cloud_status.configure(text=text))

        threading.Thread(target=worker, daemon=True).start()

    def syncSettings_(self) -> None:
        """Надсилає локальні налаштування в хмару й перезапускає її."""
        import railway_ctl

        if not railway_ctl.available():
            self.lbl_sync_status.configure(text="Не налаштовано (див. .env)")
            return

        self.lbl_sync_status.configure(text="Надсилаю…")

        def worker():
            data = settings.load()
            data["_synced_at"] = f"{time.time():.6f}"
            settings.save(data)
            ok, info = railway_ctl.push_settings(data)
            text = "✅ Надіслано, хмара перезапускається" if ok else f"⚠️ {info}"
            self.root.after(0, lambda: self.lbl_sync_status.configure(text=text))

        threading.Thread(target=worker, daemon=True).start()

    def loadBackup_(self) -> None:
        """Восстанавливает рабочие файлы из копии."""
        path = filedialog.askopenfilename(
            parent=self.window, title="Виберіть резервну копію",
            filetypes=[("ZIP архів", "*.zip")])
        if not path:
            return
        ok, info = backup.restore(path)
        if ok:
            config.reload_settings()
            self._load_settings()
            self.app.restart_radar()
            self._alert("Відновлення", f"{info.capitalize()}. Радар перезапускається.")
        else:
            self._alert("Відновлення", f"Не вдалося: {info}")

    def _alert(self, title, text) -> None:
        messagebox.showinfo(title, text, parent=self.window)

    def report_(self) -> None:
        self.app.send_report(None)
        self.refresh()

    def sendReview_(self) -> None:
        self.app.send_review(None)
        self.lbl_saved.configure(text="Смарт-звіт надсилається…")

    def reportPrev_(self) -> None:
        self.app.send_report(None, day="yesterday")
        self.refresh()
        self.lbl_saved.configure(text="Звіт надсилається…")

    def log_(self) -> None:
        import os
        try:
            os.startfile(str(config.LOGS_DIR / "monitor.log"))
        except OSError:
            pass

    def folder_(self) -> None:
        import os
        try:
            os.startfile(str(config.BASE_DIR))
        except OSError:
            pass

    # ======================================================================
    #  Обновление данных
    # ======================================================================
    def refresh(self) -> None:
        r = self.app.radar
        now = datetime.now()
        recent_high = (r.last_alert and r.last_alert[1] == "HIGH"
                       and (now - r.last_alert[0]).total_seconds()
                       < config.STATUS_ALARM_WINDOW_MIN * 60)

        if not r.running:
            state, color = "⚠️ Не працює", COLOR_ORANGE
            sub = "Радар зупинено або не зміг стартувати"
        elif r.paused:
            state, color = "⏸ Пауза", COLOR_GRAY
            sub = "Сповіщення не надсилаються"
        else:
            uptime = status_mod.human_uptime(now - r.started)
            sub = f"Працює · {len(config.CHANNELS)} каналів · {uptime}"
            if recent_high:
                state, color = "🔴 Є загроза", COLOR_RED
            elif r.alarm:
                state = f"🟡 {r.alarm[0]}"
                color = COLOR_YELLOW
                sub = f"Оголошена о {r.alarm[1]:%H:%M} · " + sub
            else:
                state, color = "🟢 Загроз немає", COLOR_GREEN

        self.lbl_state.configure(text=state, foreground=color)
        self.lbl_sub.configure(text=sub)

        if r.last_alert:
            when, _lvl, head = r.last_alert
            self.lbl_last.configure(text=f"Останнє: {head}  ({when:%H:%M})")

        if getattr(self, "report_open", False):
            try:
                import re as _re

                text = ""
                if getattr(r, "review", None):
                    text = status_mod.format_review(
                        r.review, config.CITY_MAIN_NAME, html=False) + "\n\n"
                text += _re.sub(r"<[^>]+>", "", r.build_report())
            except Exception:                               # noqa: BLE001
                text = "Звіт недоступний"
            self.lbl_counts.configure(text=text)

        self.btn_pause.configure(text="Відновити сповіщення" if r.paused
                                 else "Пауза сповіщень")

        muted = hasattr(r, "is_muted") and r.is_muted()
        self.btn_mute.configure(text=(f"🔕 Тиша до {r.mute_until:%H:%M}" if muted
                                      else "Тиша на годину"))

        # Кнопка-тумблер: підсвічена (зелений) — смарт-режим увімкнено,
        # тьмяна — кнопка «Оновити» в каналі лише перемальовує час.
        smart_on = bool(config.SMART_REVIEW)
        self.btn_smart_button.configure(
            text="🔎 Смарт-Оновити" if smart_on else "🔄 Смарт-Оновити")
        try:
            self.btn_smart_button.configure(
                foreground=COLOR_GREEN if smart_on else COLOR_TERTIARY)
        except tk.TclError:
            pass                     # деякі теми ttk ігнорують foreground кнопки

        # Тумблер: підсвічуємо активний бік, тьмяним — неактивний.
        online = config.ROLE == "backup"
        self.var_mode.set(online)
        self.lbl_local.configure(foreground=COLOR_TERTIARY if online else COLOR_GREEN)
        self.lbl_online.configure(foreground=COLOR_GREEN if online else COLOR_TERTIARY)

        msg = getattr(r, "mode_message", "") or ""
        if msg:
            self.lbl_mode_status.configure(text=msg.splitlines()[0][:60])
        elif online and getattr(r, "standby", False):
            self.lbl_mode_status.configure(text="Онлайн активний, цей пристрій мовчить")
        elif online:
            self.lbl_mode_status.configure(
                text="⚠️ Онлайн не відповідає — тимчасово працює цей пристрій")
        else:
            self.lbl_mode_status.configure(text="Активний саме цей пристрій")

    def show(self) -> None:
        self.refresh()
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
