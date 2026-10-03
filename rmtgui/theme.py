"""The app's look: dark, with the field map's yellow accent, so the tools and the website read as one thing.

apply(app) sets Qt's Fusion style, a dark palette (so check boxes, spin boxes and scroll bars follow it) and the style
sheet below. Widgets opt into the special looks by object name or property:
  #nav          the page list on the left          #brand, #brandSub   its title
  #primary      the one main button on a page      #pageNote           the grey line under a page heading
  [pill="ok|warn|fail"]  a coloured summary label
"""

import os

from PySide6.QtGui import QColor, QFont, QPalette

CHECK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check.svg").replace("\\", "/")

BG = "#0d1115"       # the field map's background
PANEL = "#141a20"
RAISED = "#1b232b"
HOVER = "#232d36"
BORDER = "#26313b"
TEXT = "#e9ecef"
MUTED = "#8b96a0"
ACCENT = "#ffd43b"   # the field map's yellow
ACCENT_HOVER = "#ffe066"
OK, WARN, FAIL, BLUE, GREY = "#8ce99a", "#ffa94d", "#ff6b6b", "#66d9e8", "#7c8791"

STYLE = f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QStackedWidget > QWidget {{ background: {BG}; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px; }}

#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
#brand {{ font-size: 15px; font-weight: 700; color: {TEXT}; }}
#brandSub {{ font-size: 11px; color: {MUTED}; }}
#nav {{ background: transparent; border: none; outline: none; font-size: 14px; }}
#nav::item {{ padding: 10px 14px; margin: 2px 8px; border-radius: 6px; color: {MUTED}; }}
#nav::item:hover {{ background: {HOVER}; color: {TEXT}; }}
#nav::item:selected {{ background: {RAISED}; color: {ACCENT}; border-left: 3px solid {ACCENT}; }}
#nav::item:disabled {{ background: transparent; color: #5d6872; font-size: 11px; font-weight: 700;
                       padding: 16px 14px 4px 14px; border: none; }}

#pageNote {{ color: {MUTED}; }}

QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; margin-top: 22px;
             padding: 14px 12px 10px 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 2px; top: 0px; padding: 0 4px; color: {ACCENT};
                    font-weight: 700; }}

QPushButton {{ background: {RAISED}; border: 1px solid {BORDER}; border-radius: 6px; padding: 7px 14px; }}
QPushButton:hover {{ background: {HOVER}; border-color: #34414d; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: #56616b; background: {PANEL}; }}
QPushButton#primary {{ background: {ACCENT}; color: {BG}; border: none; font-weight: 700; padding: 9px 22px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: #4a4426; color: #8a8160; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {ACCENT}; selection-color: {BG}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT}; }}
QLineEdit:disabled, QSpinBox:disabled {{ color: #56616b; }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {BORDER};
                               selection-background-color: {HOVER}; selection-color: {ACCENT}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QGroupBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
                                             border: 1px solid #3a4753; background: {BG}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url("{CHECK}"); }}
QCheckBox::indicator:disabled {{ background: {PANEL}; border-color: {BORDER}; }}

QTreeWidget, QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; outline: none;
                            alternate-background-color: #171e25; }}
QTreeWidget::item {{ padding: 5px 4px; }}
QListWidget::item {{ padding: 6px 8px; min-height: 20px; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {HOVER}; color: {ACCENT}; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: #1e272f; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
                        padding: 7px 6px; font-weight: 700; }}

QPlainTextEdit#log {{ background: #090c0f; border-radius: 8px; padding: 8px; }}

QProgressBar {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px; height: 20px;
                text-align: center; color: {TEXT}; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {BORDER}; border-radius: 4px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: #3a4753; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}
QSplitter::handle {{ background: transparent; height: 8px; }}

QLabel[pill="ok"] {{ background: #1d3324; color: {OK}; border-radius: 11px; font-weight: 700; }}
QLabel[pill="warn"] {{ background: #3a2a17; color: {WARN}; border-radius: 11px; font-weight: 700; }}
QLabel[pill="fail"] {{ background: #3d1d1f; color: {FAIL}; border-radius: 11px; font-weight: 700; }}

QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {BORDER}; }}
QMessageBox {{ background: {PANEL}; }}
"""


def apply(app):
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)
    p = QPalette()
    for role, colour in ((QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, TEXT),
                         (QPalette.ColorRole.Base, BG), (QPalette.ColorRole.AlternateBase, PANEL),
                         (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, RAISED),
                         (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT),
                         (QPalette.ColorRole.HighlightedText, BG), (QPalette.ColorRole.ToolTipBase, RAISED),
                         (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, MUTED),
                         (QPalette.ColorRole.Link, ACCENT)):
        p.setColor(role, QColor(colour))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor("#56616b"))
    app.setPalette(p)
    app.setStyleSheet(STYLE)


def pill(label, state):
    """Colour a summary label as a rounded badge (state: ok, warn, fail or None for plain)."""
    label.setContentsMargins(12, 3, 12, 3) if state else label.setContentsMargins(0, 0, 0, 0)
    label.setProperty("pill", state or "")
    label.style().unpolish(label)
    label.style().polish(label)
    label.updateGeometry()
