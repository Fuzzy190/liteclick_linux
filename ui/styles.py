
APP_STYLE = """
QWidget {
    background-color: #17191f;
    color: #f1f3f9;
    font-family: 'Segoe UI', sans-serif;
    font-size: 10pt;
}

QMainWindow {
    background-color: #17191f;
}

QFrame#Sidebar {
    background-color: #20232b;
    border: none;
    border-radius: 12px;
}

QLabel#AppTitle {
    font-size: 21pt;
    font-weight: bold;
    color: #ffffff;
}

QLabel#Subtitle {
    color: #9299aa;
    font-size: 9pt;
}

QFrame#Panel {
    background-color: #222630;
    border: 1px solid #303644;
    border-radius: 12px;
}

QPushButton {
    background-color: #303746;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 16px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #414b60;
}

QPushButton#StartButton {
    background-color: #2778e8;
}

QPushButton#StartButton:hover {
    background-color: #398af5;
}

QPushButton#StopButton {
    background-color: #bd3945;
}

QPushButton#StopButton:hover {
    background-color: #dc4653;
}

QLineEdit, QSpinBox, QComboBox {
    background-color: #171b23;
    color: white;
    border: 1px solid #394252;
    border-radius: 7px;
    padding: 9px;
    min-height: 20px;
}

QComboBox QAbstractItemView {
    background-color: #222630;
    color: white;
    selection-background-color: #2778e8;
}

QTabWidget::pane {
    border: 1px solid #303644;
    border-radius: 10px;
}

QTabBar::tab {
    background: #222630;
    padding: 12px 22px;
    margin-right: 4px;
    border-radius: 7px;
}

QTabBar::tab:selected {
    background: #2778e8;
    color: white;
}

QLabel#Status {
    color: #8bd5a2;
    font-weight: bold;
}
"""

# Additional component styles used by the refreshed interface.
APP_STYLE += """
QLabel#Badge {
    color: #a9c8ff;
    background-color: #202b40;
    border: 1px solid #30466a;
    border-radius: 8px;
    padding: 8px 12px;
    font-weight: bold;
}
QLabel#SectionTitle {
    font-size: 15pt;
    font-weight: bold;
    color: #ffffff;
}
QLabel#Warning {
    color: #f0ce8a;
    background-color: #342d20;
    border: 1px solid #5a4a2d;
    border-radius: 8px;
    padding: 10px;
}
QPushButton#AccentButton {
    background-color: #2b815d;
}
QPushButton#AccentButton:hover {
    background-color: #359b70;
}
QTableWidget {
    background-color: #171b23;
    alternate-background-color: #1d222d;
    color: #f1f3f9;
    border: 1px solid #394252;
    border-radius: 7px;
    gridline-color: #303644;
    selection-background-color: #294b7e;
}
QHeaderView::section {
    background-color: #2a303c;
    color: #dce3f1;
    border: none;
    padding: 8px;
    font-weight: bold;
}
QCheckBox {
    spacing: 6px;
}
"""

APP_STYLE += """
QPushButton[running="true"] {
    background-color: #168653;
    color: #ffffff;
    border: 2px solid #52d69a;
}
QPushButton[running="true"]:hover {
    background-color: #1b9b61;
}
QPushButton:disabled {
    color: #9299aa;
}
"""

APP_STYLE += """
QPushButton#ActiveButton {
    background-color: #218653;
    color: #ffffff;
    border: 2px solid #55d994;
}
QPushButton#ActiveButton:hover {
    background-color: #279b61;
}
QTableWidget::item:selected {
    background-color: #294b7e;
}
"""
