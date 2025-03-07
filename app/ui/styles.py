class Styles:
    """
    애플리케이션 UI 스타일을 정의하는 클래스
    """
    
    @staticmethod
    def get_unreal_style() -> str:
        """
        언리얼 엔진 스타일의 CSS를 반환합니다.
        """
        return """
        QWidget {
            background-color: #1a1a1a;
            color: #ffffff;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        QPushButton {
            background-color: #2a2a2a;
            border: 1px solid #3a3a3a;
            padding: 5px 10px;
            border-radius: 3px;
        }
        QPushButton:hover {
            background-color: #3a3a3a;
        }
        QPushButton:pressed {
            background-color: #4a4a4a;
        }
        QListWidget, QLineEdit, QComboBox {
            background-color: #2a2a2a;
            border: 1px solid #3a3a3a;
            border-radius: 3px;
        }
        QGroupBox {
            border: 1px solid #3a3a3a;
            border-radius: 5px;
            margin-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 3px 0 3px;
        }
        QCheckBox::indicator {
            width: 13px;
            height: 13px;
        }
        QCheckBox::indicator:unchecked {
            border: 1px solid #3a3a3a;
            background-color: #2a2a2a;
        }
        QCheckBox::indicator:checked {
            border: 1px solid #3a3a3a;
            background-color: #4a90e2;
        }
        QSlider::groove:horizontal {
            border: 1px solid #3a3a3a;
            height: 8px;
            background: #2a2a2a;
            margin: 2px 0;
        }
        QSlider::handle:horizontal {
            background: #4a90e2;
            border: 1px solid #3a3a3a;
            width: 18px;
            margin: -2px 0;
            border-radius: 3px;
        }
        """ 