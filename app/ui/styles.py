class ThemeTokens:
    """Role-based visual tokens for the desktop workspace."""

    BACKGROUND = "#0e1115"
    SURFACE = "#15191e"
    SURFACE_RAISED = "#1d232a"
    SURFACE_HOVER = "#272e36"
    BORDER = "#2b333c"
    BORDER_STRONG = "#47515d"
    TEXT = "#e8edf3"
    TEXT_MUTED = "#e8edf3"
    PRIMARY = "#4f86f7"
    PRIMARY_HOVER = "#6798fb"
    SUCCESS = "#51c878"
    WARNING = "#f1c75b"
    ERROR = "#ff6b72"
    RADIUS = 7


class Styles:
    """Application-wide modern Windows desktop stylesheet."""

    @staticmethod
    def get_unreal_style() -> str:
        # Keep the legacy method name while callers migrate to get_app_style().
        return Styles.get_app_style()

    @staticmethod
    def get_app_style() -> str:
        t = ThemeTokens
        return f"""
        QWidget {{
            background-color: {t.BACKGROUND};
            color: {t.TEXT};
            font-family: 'Segoe UI Variable', 'Segoe UI', sans-serif;
            font-size: 13px;
        }}
        QMainWindow, QStatusBar {{
            background-color: {t.BACKGROUND};
        }}
        QFrame#app-bar {{
            background-color: {t.SURFACE};
            border: none;
            border-bottom: 1px solid {t.BORDER};
        }}
        QFrame#source-panel, QFrame#preview-panel, QFrame#inspector-panel {{
            background-color: {t.SURFACE};
            border: none;
        }}
        QFrame#viewer-frame {{
            background-color: #090b0e;
            border: none;
        }}
        QFrame#cut-timeline-panel, QFrame#status-strip {{
            background-color: {t.SURFACE};
            border: none;
            border-top: 1px solid {t.BORDER};
        }}
        QLabel#app-title {{
            font-size: 17px;
            font-weight: 700;
        }}
        QLabel[role="section-title"] {{
            font-size: 14px;
            font-weight: 650;
        }}
        QLabel[role="status-ok"] {{
            color: {t.TEXT};
            background: transparent;
            border: none;
            padding: 3px 4px;
        }}
        QLabel[role="status-pending"] {{
            color: {t.TEXT};
            background: transparent;
            border: none;
            padding: 3px 4px;
        }}
        QLabel#clip-thumbnail {{
            color: #c9d8ff;
            background: #263956;
            border: 1px solid #385681;
            border-radius: 5px;
            font-size: 11px;
            font-weight: 650;
        }}
        QPushButton {{
            min-height: 22px;
            background-color: {t.SURFACE_RAISED};
            border: 1px solid {t.BORDER};
            padding: 4px 10px;
            border-radius: 5px;
        }}
        QPushButton:hover {{
            background-color: {t.SURFACE_HOVER};
            border-color: {t.BORDER_STRONG};
        }}
        QPushButton:pressed {{
            background-color: #303a46;
        }}
        QPushButton:disabled {{
            color: #68727e;
            background-color: #171b20;
            border-color: #272d35;
        }}
        QPushButton[role="primary"] {{
            background-color: {t.PRIMARY};
            border-color: {t.PRIMARY};
            color: white;
            font-weight: 650;
            min-height: 32px;
        }}
        QPushButton[role="primary"]:hover {{
            background-color: {t.PRIMARY_HOVER};
            border-color: {t.PRIMARY_HOVER};
        }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
            background-color: {t.SURFACE_RAISED};
            border: 1px solid {t.BORDER};
            border-radius: 6px;
            padding: 5px 7px;
            selection-background-color: {t.PRIMARY};
        }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
        QDoubleSpinBox:focus, QTextEdit:focus {{
            border: 1px solid {t.PRIMARY};
        }}
        QListWidget {{
            background-color: #14181d;
            border: 1px solid {t.BORDER};
            border-radius: 6px;
            outline: none;
        }}
        QListWidget::item {{
            border-bottom: 1px solid #262d35;
        }}
        QListWidget::item:selected {{
            background-color: #263956;
        }}
        QGroupBox {{
            background-color: {t.SURFACE};
            border: none;
            border-top: 1px solid {t.BORDER};
            margin-top: 12px;
            padding-top: 10px;
            font-weight: 600;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 0px;
            padding: 0 4px;
            color: {t.TEXT};
        }}
        QTabWidget::pane {{
            border: none;
            border-top: 1px solid {t.BORDER};
        }}
        QTabBar::tab {{
            min-height: 28px;
            background: transparent;
            border: none;
            padding: 3px 12px;
        }}
        QTabBar::tab:selected {{
            background: {t.SURFACE_RAISED};
            border-bottom: 2px solid {t.PRIMARY};
        }}
        QToolButton#add-sequence-button, QToolButton#remove-sequence-button {{
            min-width: 28px;
            max-width: 28px;
            min-height: 28px;
            max-height: 28px;
            padding: 0;
            margin: 0;
            background: transparent;
            border: none;
            font-size: 18px;
        }}
        QToolButton#add-sequence-button:hover, QToolButton#remove-sequence-button:hover {{
            background: {t.SURFACE_HOVER};
        }}
        QLabel#viewer-timecode {{
            font-family: 'Cascadia Mono', 'Consolas', monospace;
            font-size: 14px;
            font-weight: 600;
        }}
        QCheckBox {{
            spacing: 7px;
        }}
        QCheckBox::indicator {{
            width: 15px;
            height: 15px;
            border: 1px solid {t.BORDER_STRONG};
            border-radius: 4px;
            background: {t.SURFACE_RAISED};
        }}
        QCheckBox::indicator:checked {{
            background: {t.PRIMARY};
            border-color: {t.PRIMARY};
        }}
        QProgressBar {{
            min-height: 8px;
            max-height: 8px;
            background: {t.SURFACE_RAISED};
            border: none;
            border-radius: 4px;
            text-align: center;
            color: transparent;
        }}
        QProgressBar::chunk {{
            background: {t.PRIMARY};
            border-radius: 4px;
        }}
        QSlider::groove:horizontal {{
            height: 6px;
            background: {t.SURFACE_RAISED};
            border-radius: 3px;
        }}
        QSlider::handle:horizontal {{
            background: {t.PRIMARY};
            border: 2px solid {t.TEXT};
            width: 15px;
            margin: -6px 0;
            border-radius: 8px;
        }}
        QSplitter::handle {{
            background: transparent;
            width: 6px;
        }}
        QScrollArea {{
            border: none;
            background: transparent;
        }}
        QToolTip {{
            background: {t.SURFACE_RAISED};
            color: {t.TEXT};
            border: 1px solid {t.BORDER_STRONG};
            padding: 5px;
        }}
        """
