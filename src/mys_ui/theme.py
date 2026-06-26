"""Тема «МЫС Desktop» — брутализм: жёсткие границы, блочные «тени», моно-капс.

Перенос дизайн-системы из ``МЫС Desktop.dc.html`` / ``colors_and_type.css`` на
Qt. Токены сведены из ``themeVars()`` канвы (полупрозрачные нейтрали уплощены
над ``--bg``). Дисплейный шрифт Museo Cyrl регистрируется через ``load_fonts``.

QSS не умеет ``box-shadow``; сигнатурная жёсткая блочная тень (``Npx Npx 0 0``)
делается двумя путями: на кнопках имитируется утолщённой нижней/правой границей
(на ``:pressed`` «вдавливается»), а где нужен точный смещённый прямоугольник
(карточка vault, статус-точка, пузыри чата) — реальной тенью: ``block_shadow``
(``QGraphicsDropShadowEffect`` с нулевым радиусом) либо ручной отрисовкой.

Токены заданы для двух тем (``dark``/``light``); ``apply_theme`` ставит Fusion,
палитру и общий стиль на ``QApplication``. Тема переключается в рантайме
(``toggle_theme``) — заголовочная панель и настройки дёргают её.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect

LOGO_PATH = os.path.join(os.path.dirname(__file__), "vsc.ico")

# ---------------------------------------------------------------------------
# Токены (разрешённые в конкретные цвета — без rgba-over-bg, чтобы QSS был
# предсказуем на всех платформах). Соответствуют themeVars() из dc-канвы.
# ---------------------------------------------------------------------------

# Нейтрали — точные «плоские» эквиваленты alpha-over-bg из themeVars() канвы
# (border-2/text-2/text-3/accent-soft там полупрозрачны; здесь сведены над --bg
# для предсказуемого QSS на всех платформах).
DARK = {
    "bg": "#06112a",
    "surface": "#0d1936",
    "surface2": "#0a1530",
    "surface3": "#182547",
    "line": "#f3f3f1",
    "border2": "#2c354a",     # rgba(243,243,241,.16) over bg
    "text": "#f3f3f1",
    "text2": "#b1b4b9",       # rgba(243,243,241,.72) over bg
    "text3": "#737985",       # rgba(243,243,241,.46) over bg
    "accent": "#4d7bff",      # cobalt (единый акцент DS, dark-mode вариант)
    "accentSoft": "#141e36",  # rgba(243,243,241,.06) over bg
    "cobalt": "#4d7bff",
    "warn": "#ff6b73",
    "success": "#4ade80",
    "warning": "#e3b341",
    "barBg": "#0a1530",
    "barFg": "#f3f3f1",
    "bubbleThem": "#0d1936",
    "bubbleThemText": "#f3f3f1",
    "field": "#0d1936",       # inputs = --surface (как в канве)
}

LIGHT = {
    "bg": "#f3f3f1",
    "surface": "#ffffff",
    "surface2": "#f3f3f1",
    "surface3": "#e9e9e5",
    "line": "#06112a",
    "border2": "#d2d3d5",     # rgba(6,17,42,.14) over bg
    "text": "#06112a",
    "text2": "#575e6e",       # rgba(6,17,42,.66) over bg
    "text3": "#868b96",       # rgba(6,17,42,.46) over bg
    "accent": "#0040ff",      # cobalt (единый акцент DS)
    "accentSoft": "#e6ebfb",  # rgba(0,64,255,.07) over bg
    "cobalt": "#0040ff",
    "warn": "#da4453",
    "success": "#1a7f4f",
    "warning": "#b8860b",
    "barBg": "#06112a",
    "barFg": "#f3f3f1",
    "bubbleThem": "#ffffff",
    "bubbleThemText": "#06112a",
    "field": "#ffffff",       # inputs = --surface
}

THEMES = {"dark": DARK, "light": LIGHT}

FONT_UI = "'GOST type B', 'GOST 2.304 type A', sans-serif"
FONT_MONO = "'GOST type B', 'GOST 2.304 type A', monospace"
FONT_DISPLAY = "'GOST type B', 'GOST 2.304 type A', sans-serif"

_current = "dark"


def tokens(mode: str | None = None) -> dict:
    return THEMES[mode or _current]


def current_mode() -> str:
    return _current


# ---------------------------------------------------------------------------
# Шрифты (QSS в Qt ненадёжно резолвит fallback-списки → ключевые моно/дисплей
# шрифты выставляем QFont-ом в коде).
# ---------------------------------------------------------------------------

_FONTS_DIR = os.path.join(os.path.dirname(__file__), "fonts")
_fonts_loaded = False


def load_fonts() -> None:
    """Зарегистрировать ГОСТ-шрифты в QFontDatabase. Идемпотентно."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    for name in ("gost_2_304-81_type_b.ttf", "mipgost.ttf"):
        path = os.path.join(_FONTS_DIR, name)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    _fonts_loaded = True


def app_icon() -> QIcon:
    """Иконка приложения (окно/таскбар)."""
    return QIcon(LOGO_PATH)


def logo_pixmap(size: int) -> QPixmap:
    """Логотип МЫС, масштабированный под высоту ``size`` (с сохранением пропорций)."""
    pm = QPixmap(LOGO_PATH)
    if pm.isNull():
        return pm
    return pm.scaledToHeight(size, Qt.SmoothTransformation)


def block_shadow(widget, dx: int, dy: int, color: str):
    """Жёсткая блочная «тень» (смещённый прямоугольник без размытия).

    QSS не умеет ``box-shadow`` — повторяем сигнатурный брутализм-эффект канвы
    (``Npx Npx 0 0 var(--…)``) через ``QGraphicsDropShadowEffect`` с нулевым
    радиусом. Возвращает эффект (живёт, пока им владеет виджет)."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(0)
    eff.setOffset(dx, dy)
    eff.setColor(QColor(color))
    widget.setGraphicsEffect(eff)
    return eff


def mono_font(size: int = 11, *, bold: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "monospace"])
    f.setPixelSize(size)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.PercentageSpacing, 100 + spacing * 100)
    f.setCapitalization(QFont.AllUppercase if spacing else QFont.MixedCase)
    return f


def display_font(size: int = 18, *, weight: int = 700) -> QFont:
    f = QFont()
    f.setFamilies(["GOST type B", "GOST 2.304 type A", "sans-serif"])
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    return f


# ---------------------------------------------------------------------------
# QSS
# ---------------------------------------------------------------------------

def build_qss(t: dict) -> str:
    return f"""
* {{ outline: none; }}

QWidget {{
    background: {t['bg']};
    color: {t['text']};
    font-family: {FONT_UI};
    font-size: 16px;
}}

/* метки прозрачны по умолчанию — чипы/бейджи задают фон сами */
QLabel {{ background: transparent; }}

QToolTip {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    padding: 6px 8px;
}}

/* ---- заголовочная панель ---- */
QWidget#TitleBar {{
    background: {t['barBg']};
    border-bottom: 2px solid {t['line']};
}}
QLabel#BrandMark {{
    color: {t['text']};
    font-family: {FONT_DISPLAY};
    font-weight: 700;
    font-size: 25px;
    letter-spacing: 1px;
}}
QWidget#TitleBar QLabel#BrandMark {{
    color: {t['barFg']};
}}
QLabel#BrandSub {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}

/* ---- панель инструментов ---- */
QWidget#Toolbar {{
    background: {t['surface2']};
    border-bottom: 2px solid {t['line']};
}}
/* вкладки режима теперь BrutalButton (checkable) — см. widgets/brutal.py */
QLabel#Chip {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['border2']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
    padding: 6px 12px;
}}
/* кнопки тулбара/действий теперь рисует BrutalButton (widgets/brutal.py) */

/* ---- боковая панель (список диалогов) ---- */
QWidget#Sidebar {{
    background: {t['surface2']};
}}
/* кобальтовый разделитель между комнатами и чатом — ручка сплиттера */
QSplitter#MainSplit::handle:horizontal {{
    background: {t['accent']};
    width: 3px;
}}
QWidget#SidebarHeader {{
    border-bottom: 2px solid {t['line']};
}}
QLabel#ListTitle {{
    color: {t['text']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
}}
QLabel#ListCount {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
}}
QListWidget#ConvList {{
    background: {t['surface2']};
    border: none;
    outline: none;
}}
QListWidget#ConvList::item {{
    color: {t['text']};
    border-bottom: 1px solid {t['border2']};
    padding: 12px 16px;
}}
QListWidget#ConvList::item:hover {{
    background: {t['surface3']};
}}
QListWidget#ConvList::item:selected {{
    background: {t['accentSoft']};
    border-left: 3px solid {t['accent']};
    color: {t['text']};
}}

/* ---- чат ---- */
QWidget#ChatPane {{ background: {t['bg']}; }}
QWidget#ChatHeader {{
    background: {t['surface']};
    border-bottom: 2px solid {t['line']};
}}
QLabel#ChatName {{ color: {t['text']}; font-size: 20px; font-weight: 600; }}
QLabel#ChatSub {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}
QLabel#FounderBadge {{
    background: {t['cobalt']};
    color: #ffffff;
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 11px;
    padding: 3px 6px;
}}
QLabel#ChatBadge {{
    color: {t['text3']};
    border: 1px solid {t['border2']};
    font-family: {FONT_MONO};
    font-size: 13px;
    padding: 4px 8px;
}}
QWidget#Disclaimer {{
    background: {t['accentSoft']};
    border-bottom: 1px solid {t['border2']};
}}
QLabel#DisclaimerText {{ color: {t['text2']}; font-size: 16px; background: transparent; }}
QListWidget#ChatView {{
    background: {t['bg']};
    border: none;
    outline: none;
}}
QLabel#EmptyState {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}

/* ---- строка ввода ---- */
QWidget#InputBar {{
    background: {t['surface']};
    border-top: 2px solid {t['line']};
}}
/* ---- поля ввода ---- */
QLineEdit {{
    background: {t['field']};
    color: {t['text']};
    border: 1px solid {t['line']};
    padding: 11px 14px;
    selection-background-color: {t['accent']};
}}
/* фокус: граница остаётся ink — кобальтовую смещённую тень даёт BrutalLineEdit */
QLineEdit:focus {{ border: 1px solid {t['line']}; }}
QLineEdit#MsgField {{ font-size: 16px; }}

/* ---- статус-бар ---- */
QWidget#StatusBar {{
    background: {t['surface2']};
    border-top: 2px solid {t['line']};
}}
QLabel#StatusText {{
    color: {t['text2']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}
QLabel#StatusMono {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}
QLabel#StatusDot {{ background: {t['success']}; }}

/* ---- vault / окно входа ---- */
QWidget#VaultCard {{
    background: {t['surface']};
    border: 2px solid {t['line']};
}}
QLabel#VaultTitle {{
    color: {t['text2']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
}}
QLabel#FieldLabel {{
    color: {t['text2']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
}}
QWidget#WarnBox {{
    background: {t['accentSoft']};
    border: 1px solid {t['border2']};
}}
QLabel#WarnBoxText {{ color: {t['text2']}; font-size: 16px; background: transparent; }}
QLabel#ErrorText {{
    color: {t['warn']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}
QLabel#SuccessText {{
    color: {t['success']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}
QLabel#LinkText {{
    color: {t['accent']};
    font-family: {FONT_MONO};
    font-size: 13px;
}}

/* ---- диалоги / секции настроек ---- */
QDialog {{ background: {t['surface']}; }}
/* безрамочный диалог: ink-рамка (фон под 2px-полями) + ink-строка заголовка */
QDialog#FramelessDialog {{ background: {t['line']}; }}
QWidget#DialogBody {{ background: {t['surface']}; }}
QWidget#DialogBar {{ background: {t['barBg']}; }}
QLabel#DialogBarTitle {{
    color: {t['barFg']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 1px;
}}
QLabel#DialogTitle {{
    color: {t['text']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 20px;
    border-bottom: 2px solid {t['line']};
    padding-bottom: 12px;
}}
QLabel#SectionLabel {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
}}
QFrame#Sep {{ border: none; border-top: 1px solid {t['border2']}; }}
QCheckBox {{ color: {t['text2']}; font-size: 16px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {t['line']};
    background: {t['field']};
}}
QCheckBox::indicator:checked {{ background: {t['accent']}; }}

/* ---- скроллбары ---- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t['border2']}; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {t['text3']}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t['border2']}; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def _apply_palette(app, t: dict) -> None:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t["bg"]))
    p.setColor(QPalette.WindowText, QColor(t["text"]))
    p.setColor(QPalette.Base, QColor(t["field"]))
    p.setColor(QPalette.AlternateBase, QColor(t["surface2"]))
    p.setColor(QPalette.Text, QColor(t["text"]))
    p.setColor(QPalette.Button, QColor(t["surface"]))
    p.setColor(QPalette.ButtonText, QColor(t["text"]))
    p.setColor(QPalette.Highlight, QColor(t["accent"]))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ToolTipBase, QColor(t["surface"]))
    p.setColor(QPalette.ToolTipText, QColor(t["text"]))
    p.setColor(QPalette.PlaceholderText, QColor(t["text3"]))
    app.setPalette(p)


def apply_theme(app, mode: str = "dark") -> None:
    """Поставить тему на приложение: Fusion + палитра + общий QSS."""
    global _current
    _current = mode if mode in THEMES else "dark"
    t = THEMES[_current]
    load_fonts()
    app.setStyle("Fusion")
    base = QFont()
    base.setFamilies(["GOST type B", "GOST 2.304 type A", "sans-serif"])
    base.setPixelSize(16)
    app.setFont(base)
    _apply_palette(app, t)
    app.setStyleSheet(build_qss(t))


def set_theme(app, mode: str) -> None:
    apply_theme(app, mode)


def toggle_theme(app) -> str:
    """Переключить dark↔light и применить. Возвращает новый режим."""
    new = "light" if _current == "dark" else "dark"
    apply_theme(app, new)
    return new


# Совместимость со старым именем (app.py исторически звал apply_dark_theme).
def apply_dark_theme(app) -> None:
    apply_theme(app, "dark")
