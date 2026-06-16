"""
Global stylesheet for Quant Chart.
All colors, fonts, and widget styles live here.

Color palette (inspired by deepcharts / dark navy trading UI):
  BG_DEEP    #0D1117   -- outermost background
  BG_BASE    #111827   -- main window background
  BG_PANEL   #1A2236   -- group boxes, panels
  BG_INPUT   #1F2D40   -- inputs, combos, line edits
  BG_HOVER   #243550   -- hover state
  BG_PRESS   #2A3D5E   -- pressed state
  BORDER     #2A3A52   -- subtle borders
  ACCENT     #3B8FD4   -- primary accent (blue)
  ACCENT_HOV #4FA3E8   -- accent hover
  TEXT_PRI   #E8EDF5   -- primary text
  TEXT_SEC   #7A8BA8   -- secondary / label text
  TEXT_DIM   #4A5A72   -- dimmed text
  SUCCESS    #2ECC71   -- green
  DANGER     #E74C3C   -- red
"""

PALETTE = {
    "BG_DEEP":    "#0D1117",
    "BG_BASE":    "#111827",
    "BG_PANEL":   "#1A2236",
    "BG_INPUT":   "#1F2D40",
    "BG_HOVER":   "#243550",
    "BG_PRESS":   "#2A3D5E",
    "BORDER":     "#2A3A52",
    "ACCENT":     "#3B8FD4",
    "ACCENT_HOV": "#4FA3E8",
    "TEXT_PRI":   "#E8EDF5",
    "TEXT_SEC":   "#7A8BA8",
    "TEXT_DIM":   "#4A5A72",
    "SUCCESS":    "#2ECC71",
    "DANGER":     "#E74C3C",
}

FONT_FAMILY = "Segoe UI"   # Windows; Qt falls back gracefully on other OS
FONT_SIZE   = 10           # pt

MAIN_STYLESHEET = f"""
/* ── Base ─────────────────────────────────────────────────────────── */
QMainWindow, QDialog, QWidget {{
    background-color: {PALETTE['BG_BASE']};
    color: {PALETTE['TEXT_PRI']};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}pt;
}}

/* ── Group boxes ───────────────────────────────────────────────────── */
QGroupBox {{
    background-color: {PALETTE['BG_PANEL']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 6px;
    margin-top: 20px;
    padding: 12px 10px 10px 10px;
    font-size: {FONT_SIZE}pt;
    font-weight: 600;
    color: {PALETTE['TEXT_SEC']};
    letter-spacing: 0.5px;
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    left: 10px;
    top: 3px;
    color: {PALETTE['TEXT_SEC']};
}}

/* ── Labels ────────────────────────────────────────────────────────── */
QLabel {{
    color: {PALETTE['TEXT_SEC']};
    background: transparent;
}}

/* ── Line edit ─────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {PALETTE['BG_INPUT']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {PALETTE['TEXT_PRI']};
    selection-background-color: {PALETTE['ACCENT']};
}}
QLineEdit:focus {{
    border: 1px solid {PALETTE['ACCENT']};
}}

/* ── Combo box ─────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {PALETTE['BG_INPUT']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {PALETTE['TEXT_PRI']};
    min-height: 24px;
}}
QComboBox:hover {{
    border: 1px solid {PALETTE['ACCENT']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PALETTE['TEXT_SEC']};
    width: 0;
    height: 0;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {PALETTE['BG_INPUT']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 4px;
    color: {PALETTE['TEXT_PRI']};
    selection-background-color: {PALETTE['ACCENT']};
    outline: none;
}}

/* ── Date / Time edits ─────────────────────────────────────────────── */
QDateEdit, QTimeEdit {{
    background-color: {PALETTE['BG_INPUT']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {PALETTE['TEXT_PRI']};
    min-height: 24px;
}}
QDateEdit:focus, QTimeEdit:focus {{
    border: 1px solid {PALETTE['ACCENT']};
}}
QDateEdit::drop-down, QTimeEdit::drop-down {{
    border: none;
    width: 20px;
}}
QDateEdit::down-arrow, QTimeEdit::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PALETTE['TEXT_SEC']};
    width: 0;
    height: 0;
}}
QCalendarWidget {{
    background-color: {PALETTE['BG_PANEL']};
    color: {PALETTE['TEXT_PRI']};
}}
QCalendarWidget QAbstractItemView {{
    background-color: {PALETTE['BG_PANEL']};
    selection-background-color: {PALETTE['ACCENT']};
    color: {PALETTE['TEXT_PRI']};
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {PALETTE['BG_INPUT']};
}}
QCalendarWidget QToolButton {{
    background-color: transparent;
    color: {PALETTE['TEXT_PRI']};
}}

/* ── Spin box ──────────────────────────────────────────────────────── */
QSpinBox {{
    background-color: {PALETTE['BG_INPUT']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 4px;
    padding: 4px 8px;
    color: {PALETTE['TEXT_PRI']};
    min-height: 24px;
}}
QSpinBox:focus {{
    border: 1px solid {PALETTE['ACCENT']};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {PALETTE['BG_HOVER']};
    border: none;
    width: 18px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background-color: {PALETTE['ACCENT']};
}}

/* ── Push buttons ──────────────────────────────────────────────────── */
QPushButton {{
    background-color: {PALETTE['BG_INPUT']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 5px;
    padding: 6px 16px;
    color: {PALETTE['TEXT_PRI']};
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {PALETTE['BG_HOVER']};
    border: 1px solid {PALETTE['ACCENT']};
    color: {PALETTE['TEXT_PRI']};
}}
QPushButton:pressed {{
    background-color: {PALETTE['BG_PRESS']};
    border: 1px solid {PALETTE['ACCENT']};
}}
QPushButton:checked {{
    background-color: {PALETTE['BG_PRESS']};
    border: 1px solid {PALETTE['ACCENT']};
    color: {PALETTE['ACCENT_HOV']};
}}

/* Chart launch buttons get the accent treatment */
QPushButton[chartButton="true"] {{
    background-color: {PALETTE['BG_PANEL']};
    border: 1px solid {PALETTE['BORDER']};
    border-radius: 6px;
    color: {PALETTE['TEXT_PRI']};
    font-size: 11pt;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QPushButton[chartButton="true"]:hover {{
    background-color: {PALETTE['BG_HOVER']};
    border: 1px solid {PALETTE['ACCENT']};
    color: {PALETTE['ACCENT_HOV']};
}}
QPushButton[chartButton="true"]:pressed {{
    background-color: {PALETTE['BG_PRESS']};
}}

/* ── Dialog button box ─────────────────────────────────────────────── */
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}

/* ── Scrollbars ────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {PALETTE['BG_BASE']};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {PALETTE['BORDER']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {PALETTE['ACCENT']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ── Tooltip ───────────────────────────────────────────────────────── */
QToolTip {{
    background-color: {PALETTE['BG_PANEL']};
    border: 1px solid {PALETTE['BORDER']};
    color: {PALETTE['TEXT_PRI']};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* ── Message box ───────────────────────────────────────────────────── */
QMessageBox {{
    background-color: {PALETTE['BG_BASE']};
}}
QMessageBox QLabel {{
    color: {PALETTE['TEXT_PRI']};
}}
"""
