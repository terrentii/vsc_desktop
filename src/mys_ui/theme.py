"""Тема «МЫС Desktop» — брутализм: жёсткие границы, блочные «тени», моно-капс.

Перенос дизайн-системы из ``МЫС Desktop.dc.html`` / ``colors_and_type.css`` на
Qt. Поскольку QSS не умеет ``box-shadow``, блочная тень имитируется утолщённой
нижней/правой границей у акцентных кнопок (на ``:pressed`` граница «вдавливается»).

Токены заданы для двух тем (``dark``/``light``); ``apply_theme`` ставит Fusion,
палитру и общий стиль на ``QApplication``. Тема переключается в рантайме
(``toggle_theme``) — заголовочная панель и настройки дёргают её.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette

# ---------------------------------------------------------------------------
# Токены (разрешённые в конкретные цвета — без rgba-over-bg, чтобы QSS был
# предсказуем на всех платформах). Соответствуют themeVars() из dc-канвы.
# ---------------------------------------------------------------------------

DARK = {
    "bg": "#06112a",
    "surface": "#0d1936",
    "surface2": "#0a1530",
    "surface3": "#182547",
    "line": "#f3f3f1",
    "border2": "#2c3a59",
    "text": "#f3f3f1",
    "text2": "#aeb4c0",
    "text3": "#7d8694",
    "accent": "#57a7dd",      # lighten(#007acc, .34)
    "accentSoft": "#111c33",
    "cobalt": "#4d7bff",
    "warn": "#ff6b73",
    "success": "#4ade80",
    "warning": "#e3b341",
    "barBg": "#0a1530",
    "barFg": "#f3f3f1",
    "bubbleThem": "#0d1936",
    "bubbleThemText": "#f3f3f1",
    "field": "#0a1530",
}

LIGHT = {
    "bg": "#f3f3f1",
    "surface": "#ffffff",
    "surface2": "#f3f3f1",
    "surface3": "#e9e9e5",
    "line": "#06112a",
    "border2": "#d3d6db",
    "text": "#06112a",
    "text2": "#4a5260",
    "text3": "#767c88",
    "accent": "#007acc",
    "accentSoft": "#ebf4fb",
    "cobalt": "#0040ff",
    "warn": "#da4453",
    "success": "#1a7f4f",
    "warning": "#b8860b",
    "barBg": "#06112a",
    "barFg": "#f3f3f1",
    "bubbleThem": "#ffffff",
    "bubbleThemText": "#06112a",
    "field": "#ffffff",
}

THEMES = {"dark": DARK, "light": LIGHT}

# Семейства из дизайн-системы с разумными запасными вариантами (Museo/Inter/
# JetBrains в системе может не быть — Qt подберёт ближайшее).
FONT_UI = "Inter, 'Segoe UI', 'DejaVu Sans', sans-serif"
FONT_MONO = "'JetBrains Mono', 'DejaVu Sans Mono', monospace"
FONT_DISPLAY = "'Museo Cyrl', Inter, 'Segoe UI', sans-serif"

_current = "dark"


def tokens(mode: str | None = None) -> dict:
    return THEMES[mode or _current]


def current_mode() -> str:
    return _current


# ---------------------------------------------------------------------------
# Шрифты (QSS в Qt ненадёжно резолвит fallback-списки → ключевые моно/дисплей
# шрифты выставляем QFont-ом в коде).
# ---------------------------------------------------------------------------

def mono_font(size: int = 11, *, bold: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont()
    f.setStyleHint(QFont.Monospace)
    f.setFamilies(["JetBrains Mono", "DejaVu Sans Mono", "monospace"])
    f.setPixelSize(size)
    f.setBold(bold)
    if spacing:
        f.setLetterSpacing(QFont.PercentageSpacing, 100 + spacing * 100)
    f.setCapitalization(QFont.AllUppercase if spacing else QFont.MixedCase)
    return f


def display_font(size: int = 18, *, weight: int = 700) -> QFont:
    f = QFont()
    f.setFamilies(["Museo Cyrl", "Inter", "Segoe UI", "sans-serif"])
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
    font-size: 13px;
}}

/* метки прозрачны по умолчанию — чипы/бейджи задают фон сами */
QLabel {{ background: transparent; }}

QToolTip {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    padding: 4px 8px;
}}

/* ---- заголовочная панель ---- */
QWidget#TitleBar {{
    background: {t['barBg']};
    border-bottom: 2px solid {t['line']};
}}
QLabel#BrandMark {{
    color: {t['barFg']};
    font-family: {FONT_DISPLAY};
    font-weight: 700;
    font-size: 18px;
    letter-spacing: 1px;
}}
QLabel#BrandSub {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 10px;
}}
QPushButton#ThemeToggle {{
    background: transparent;
    color: {t['barFg']};
    border: 1px solid transparent;
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 11px;
    padding: 4px 10px;
}}
QPushButton#ThemeToggle:hover {{
    background: {t['surface3']};
    border: 1px solid {t['border2']};
}}

/* ---- панель инструментов ---- */
QWidget#Toolbar {{
    background: {t['surface2']};
    border-bottom: 2px solid {t['line']};
}}
QPushButton#ModeTab {{
    background: {t['surface']};
    color: {t['text2']};
    border: 1px solid {t['line']};
    border-bottom: 3px solid {t['line']};
    border-right: 3px solid {t['line']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 12px;
    padding: 6px 18px;
}}
QPushButton#ModeTab:checked {{
    background: {t['accent']};
    color: #ffffff;
}}
QPushButton#ModeTab:pressed {{
    border-bottom: 1px solid {t['line']};
    border-right: 1px solid {t['line']};
}}
QLabel#Chip {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['border2']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 11px;
    padding: 5px 11px;
}}
QPushButton#BarBtn {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 10px;
    padding: 6px 13px;
}}
QPushButton#BarBtn:hover {{
    background: {t['line']};
    color: {t['bg']};
}}
QPushButton#WarnBtn {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 10px;
    padding: 6px 13px;
}}
QPushButton#WarnBtn:hover {{
    background: {t['warn']};
    color: #ffffff;
    border-color: {t['warn']};
}}

/* ---- боковая панель (список диалогов) ---- */
QWidget#Sidebar {{
    background: {t['surface2']};
    border-right: 2px solid {t['line']};
}}
QWidget#SidebarHeader {{
    border-bottom: 2px solid {t['line']};
}}
QLabel#ListTitle {{
    color: {t['text']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 11px;
}}
QLabel#ListCount {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 10px;
}}
QListWidget#ConvList {{
    background: {t['surface2']};
    border: none;
    outline: none;
}}
QListWidget#ConvList::item {{
    color: {t['text']};
    border-bottom: 1px solid {t['border2']};
    padding: 11px 14px;
}}
QListWidget#ConvList::item:hover {{
    background: {t['surface3']};
}}
QListWidget#ConvList::item:selected {{
    background: {t['accentSoft']};
    border-left: 3px solid {t['accent']};
    color: {t['text']};
}}

/* ---- акцентная (главная) кнопка с блочной «тенью» ---- */
QPushButton#PrimaryBtn {{
    background: {t['accent']};
    color: #ffffff;
    border: 1px solid {t['line']};
    border-bottom: 3px solid {t['line']};
    border-right: 3px solid {t['line']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 11px;
    padding: 10px 16px;
}}
QPushButton#PrimaryBtn:pressed {{
    border-bottom: 1px solid {t['line']};
    border-right: 1px solid {t['line']};
}}
QPushButton#GhostBtn {{
    background: transparent;
    color: {t['text2']};
    border: 1px solid {t['border2']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 11px;
    padding: 9px 16px;
}}
QPushButton#GhostBtn:hover {{ border-color: {t['text2']}; }}

/* ---- чат ---- */
QWidget#ChatPane {{ background: {t['bg']}; }}
QWidget#ChatHeader {{
    background: {t['surface']};
    border-bottom: 2px solid {t['line']};
}}
QLabel#ChatName {{ color: {t['text']}; font-size: 15px; font-weight: 600; }}
QLabel#ChatSub {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 10px;
}}
QLabel#FounderBadge {{
    background: {t['cobalt']};
    color: #ffffff;
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 9px;
    padding: 2px 6px;
}}
QLabel#ChatBadge {{
    color: {t['text3']};
    border: 1px solid {t['border2']};
    font-family: {FONT_MONO};
    font-size: 10px;
    padding: 4px 9px;
}}
QWidget#Disclaimer {{
    background: {t['accentSoft']};
    border-bottom: 1px solid {t['border2']};
}}
QLabel#DisclaimerText {{ color: {t['text2']}; font-size: 12px; background: transparent; }}
QListWidget#ChatView {{
    background: {t['bg']};
    border: none;
    outline: none;
}}
QLabel#EmptyState {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 11px;
}}

/* ---- строка ввода ---- */
QWidget#InputBar {{
    background: {t['surface']};
    border-top: 2px solid {t['line']};
}}
QPushButton#AttachBtn {{
    background: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['line']};
    font-size: 15px;
}}
QPushButton#AttachBtn:hover {{ background: {t['line']}; color: {t['bg']}; }}

/* ---- поля ввода ---- */
QLineEdit {{
    background: {t['field']};
    color: {t['text']};
    border: 1px solid {t['line']};
    padding: 9px 12px;
    selection-background-color: {t['accent']};
}}
QLineEdit:focus {{ border: 1px solid {t['accent']}; }}
QLineEdit#MsgField {{ font-size: 13px; }}

/* ---- статус-бар ---- */
QWidget#StatusBar {{
    background: {t['surface2']};
    border-top: 2px solid {t['line']};
}}
QLabel#StatusText {{
    color: {t['text2']};
    font-family: {FONT_MONO};
    font-size: 10px;
}}
QLabel#StatusMono {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-size: 10px;
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
    font-size: 11px;
}}
QLabel#FieldLabel {{
    color: {t['text2']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 10px;
}}
QWidget#WarnBox {{
    background: {t['accentSoft']};
    border: 1px solid {t['border2']};
}}
QLabel#WarnBoxText {{ color: {t['text2']}; font-size: 12px; background: transparent; }}
QLabel#ErrorText {{
    color: {t['warn']};
    font-family: {FONT_MONO};
    font-size: 11px;
}}
QLabel#SuccessText {{
    color: {t['success']};
    font-family: {FONT_MONO};
    font-size: 11px;
}}
QLabel#LinkText {{
    color: {t['accent']};
    font-family: {FONT_MONO};
    font-size: 10px;
}}

/* ---- диалоги / секции настроек ---- */
QDialog {{ background: {t['surface']}; }}
QLabel#DialogTitle {{
    color: {t['text']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 13px;
    border-bottom: 2px solid {t['line']};
    padding-bottom: 10px;
}}
QLabel#SectionLabel {{
    color: {t['text3']};
    font-family: {FONT_MONO};
    font-weight: 700;
    font-size: 10px;
}}
QFrame#Sep {{ border: none; border-top: 1px solid {t['border2']}; }}
QCheckBox {{ color: {t['text2']}; font-size: 12px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
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
    app.setStyle("Fusion")
    base = QFont()
    base.setFamilies(["Inter", "Segoe UI", "DejaVu Sans", "sans-serif"])
    base.setPixelSize(13)
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
