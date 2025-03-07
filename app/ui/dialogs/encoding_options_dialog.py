from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QComboBox, QPushButton

class EncodingOptionsDialog(QDialog):
    def __init__(self, parent=None, encoding_options=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 옵션")
        self.encoding_options = encoding_options or {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 인코딩 옵션 그룹
        options_group = QGroupBox("인코딩 옵션")
        options_layout = QVBoxLayout()

        encoding_options = [
            ("c:v", ["libx264", "libx265", "none"]),
            ("pix_fmt", ["yuv420p", "yuv422p", "yuv444p", "none"]),
            ("colorspace", ["bt709", "bt2020nc", "none"]),
            ("color_primaries", ["bt709", "bt2020", "none"]),
            ("color_trc", ["bt709", "bt2020-10", "none"]),
            ("color_range", ["limited", "full", "none"])
        ]

        self.option_widgets = {}
        for option, values in encoding_options:
            self.create_option_widget(options_layout, option, values)

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # 확인/취소 버튼
        button_box = QHBoxLayout()
        ok_button = QPushButton("확인")
        cancel_button = QPushButton("취소")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_box.addWidget(ok_button)
        button_box.addWidget(cancel_button)
        layout.addLayout(button_box)

    def create_option_widget(self, layout, option, values):
        hbox = QHBoxLayout()
        label = QLabel(option)
        combo = QComboBox()
        combo.addItems(values)
        current_value = self.encoding_options.get(option, values[0])
        combo.setCurrentText(current_value)
        hbox.addWidget(label)
        hbox.addWidget(combo)
        layout.addLayout(hbox)
        self.option_widgets[option] = combo

    def get_options(self):
        options = {}
        for option, combo in self.option_widgets.items():
            if combo.currentText() != "none":
                options[option] = combo.currentText()
        return options 