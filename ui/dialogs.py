from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox, QLabel,
    QComboBox, QCheckBox, QLineEdit, QSpinBox, QProgressBar, QFileDialog
)
from PySide6.QtCore import QTimer, QTime
from typing import Dict, List, Optional
from color_management import get_cached_manager

class ColorOptionsDialog(QDialog):
    """색상 및 컬러 매니지먼트 옵션 다이얼로그."""

    def __init__(self, current_options: Dict[str, str], color_options: Dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("색상 옵션")
        self.setMinimumWidth(420)
        self.options = current_options.copy()
        self.color_options = (color_options or {}).copy()

        self.color_manager = None
        self._ensure_color_defaults()

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_ffmpeg_color_group())
        layout.addWidget(self._build_color_management_group())

        button_box = QHBoxLayout()
        ok_button = QPushButton("확인")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("취소")
        cancel_button.clicked.connect(self.reject)
        button_box.addStretch()
        button_box.addWidget(ok_button)
        button_box.addWidget(cancel_button)
        layout.addLayout(button_box)

    # ------------------------------------------------------------------
    # FFmpeg 색상 파라미터
    # ------------------------------------------------------------------
    def _build_ffmpeg_color_group(self) -> QGroupBox:
        group = QGroupBox("FFmpeg 색상 파라미터")
        group_layout = QVBoxLayout(group)
        self.option_widgets = {}
        color_options = [
            ("colorspace", ["bt709", "bt2020nc", "none"]),
            ("color_primaries", ["bt709", "bt2020", "none"]),
            ("color_trc", ["bt709", "bt2020-10", "none"]),
            ("color_range", ["limited", "full", "none"]),
        ]

        for option, values in color_options:
            hbox = QHBoxLayout()
            label = QLabel(option)
            combo = QComboBox()
            combo.addItems(values)
            current_value = self.options.get(option)
            if current_value in values:
                combo.setCurrentText(current_value)
            combo.currentTextChanged.connect(lambda value, opt=option: self.update_option(opt, value))
            hbox.addWidget(label)
            hbox.addWidget(combo)
            group_layout.addLayout(hbox)
            self.option_widgets[option] = combo

        return group

    # ------------------------------------------------------------------
    # 컬러 매니지먼트 UI
    # ------------------------------------------------------------------
    def _build_color_management_group(self) -> QGroupBox:
        group = QGroupBox("컬러 매니지먼트 (OCIO)")
        layout = QVBoxLayout(group)

        self.color_checkbox = QCheckBox("OCIO 컬러 매니지먼트 활성화")
        self.color_checkbox.setChecked(bool(self.color_options.get("enabled")))
        self.color_checkbox.toggled.connect(self._update_color_ui_state)
        layout.addWidget(self.color_checkbox)

        config_layout = QHBoxLayout()
        config_layout.addWidget(QLabel("Config:"))
        self.color_config_edit = QLineEdit(self.color_options.get("config_path", ""))
        self.color_config_edit.setPlaceholderText("환경변수 OCIO 사용")
        self.color_config_edit.editingFinished.connect(self._on_color_config_changed)
        config_layout.addWidget(self.color_config_edit)
        config_button = QPushButton("찾기")
        config_button.clicked.connect(self._browse_color_config)
        config_layout.addWidget(config_button)
        layout.addLayout(config_layout)

        input_layout = QHBoxLayout()
        input_layout.addWidget(QLabel("Input Space:"))
        self.color_input_combo = QComboBox()
        self.color_input_combo.currentTextChanged.connect(self._on_color_input_changed)
        input_layout.addWidget(self.color_input_combo)
        layout.addLayout(input_layout)

        display_layout = QHBoxLayout()
        display_layout.addWidget(QLabel("Display:"))
        self.color_display_combo = QComboBox()
        self.color_display_combo.currentTextChanged.connect(self._on_color_display_changed)
        display_layout.addWidget(self.color_display_combo)
        layout.addLayout(display_layout)

        view_layout = QHBoxLayout()
        view_layout.addWidget(QLabel("View:"))
        self.color_view_combo = QComboBox()
        self.color_view_combo.currentTextChanged.connect(self._on_color_view_changed)
        view_layout.addWidget(self.color_view_combo)
        layout.addLayout(view_layout)

        lut_layout = QHBoxLayout()
        lut_layout.addWidget(QLabel("LUT Size:"))
        self.color_lut_spin = QSpinBox()
        self.color_lut_spin.setRange(16, 129)
        self.color_lut_spin.setValue(int(self.color_options.get("lut_size", 33)))
        self.color_lut_spin.valueChanged.connect(self._on_color_lut_changed)
        lut_layout.addWidget(self.color_lut_spin)
        layout.addLayout(lut_layout)

        self.color_warning_label = QLabel()
        self.color_warning_label.setWordWrap(True)
        layout.addWidget(self.color_warning_label)

        self._refresh_color_manager()
        self._update_color_ui_state()
        return group

    def _ensure_color_defaults(self):
        manager = get_cached_manager(self.color_options.get("config_path", ""))
        self.color_manager = manager
        default_input, default_display, default_view = manager.get_default_io()
        if not self.color_options.get("input_space"):
            self.color_options["input_space"] = "Auto"
        if not self.color_options.get("output_display"):
            self.color_options["output_display"] = default_display
        if not self.color_options.get("output_view"):
            self.color_options["output_view"] = default_view
        if "lut_size" not in self.color_options:
            self.color_options["lut_size"] = 33

    def _refresh_color_manager(self):
        self._ensure_color_defaults()
        manager = get_cached_manager(self.color_options.get("config_path", ""))
        self.color_manager = manager
        inputs = manager.list_input_spaces()
        if "Auto" not in inputs:
            inputs = ["Auto"] + inputs
        self._set_combo_items(
            self.color_input_combo,
            inputs,
            self.color_options.get("input_space", "Auto")
        )
        self.color_options["input_space"] = self.color_input_combo.currentText()

        displays = manager.list_displays()
        display_selection = self.color_options.get("output_display") or (displays[0] if displays else "Rec.709")
        self._set_combo_items(self.color_display_combo, displays or [display_selection], display_selection)
        self.color_options["output_display"] = self.color_display_combo.currentText()

        self._populate_view_combo()
        self._update_color_warning()

    def _populate_view_combo(self):
        display = self.color_display_combo.currentText()
        views = self.color_manager.list_views(display) if self.color_manager else []
        view_selection = self.color_options.get("output_view") or (views[0] if views else "Standard")
        self._set_combo_items(self.color_view_combo, views or [view_selection], view_selection)
        self.color_options["output_view"] = self.color_view_combo.currentText()

    def _set_combo_items(self, combo: QComboBox, items: List[str], selected: str):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        if selected in items:
            combo.setCurrentText(selected)
        elif items:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _update_color_warning(self):
        if not self.color_manager or self.color_manager.is_available:
            self.color_warning_label.setText("")
        else:
            self.color_warning_label.setText("PyOpenColorIO가 없어 기본 변환만 사용됩니다.")

    def _update_color_ui_state(self):
        enabled = self.color_checkbox.isChecked()
        widgets = [
            self.color_config_edit,
            self.color_display_combo,
            self.color_view_combo,
            self.color_input_combo,
            self.color_lut_spin,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)
        if enabled and not self.color_manager:
            self._refresh_color_manager()

    def _browse_color_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "OCIO Config 선택", self.color_config_edit.text(), "OCIO Config (*.ocio)")
        if path:
            self.color_config_edit.setText(path)
            self._on_color_config_changed()

    def _on_color_config_changed(self):
        self.color_options["config_path"] = self.color_config_edit.text().strip()
        self._refresh_color_manager()

    def _on_color_display_changed(self, value: str):
        self.color_options["output_display"] = value
        self._populate_view_combo()

    def _on_color_input_changed(self, value: str):
        self.color_options["input_space"] = value

    def _on_color_view_changed(self, value: str):
        self.color_options["output_view"] = value

    def _on_color_lut_changed(self, value: int):
        self.color_options["lut_size"] = value

    def update_option(self, option: str, value: str):
        if value != "none":
            self.options[option] = value
        else:
            self.options.pop(option, None)

    def get_options(self) -> Dict[str, str]:
        return self.options

    def get_color_options(self) -> Dict[str, str]:
        return self.color_options

    def accept(self):
        self.color_options["enabled"] = self.color_checkbox.isChecked()
        self.color_options["config_path"] = self.color_config_edit.text().strip()
        self.color_options["input_space"] = self.color_input_combo.currentText()
        self.color_options["output_display"] = self.color_display_combo.currentText()
        self.color_options["output_view"] = self.color_view_combo.currentText()
        self.color_options["lut_size"] = self.color_lut_spin.value()
        super().accept()

class EncodingProgressDialog(QDialog):
    """
    인코딩 진행 상황을 표시하는 다이얼로그
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 진행 상황")
        self.setFixedSize(300, 150)  # 높이를 늘려서 경과 시간 표시

        layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.elapsed_time_label = QLabel("경과 시간: 00:00:00")
        layout.addWidget(self.elapsed_time_label)

        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed_time)
        self.start_time = QTime()

    def start_timer(self):
        self.start_time = QTime.currentTime()
        self.timer.start(1000)  # 1초마다 업데이트

    def stop_timer(self):
        self.timer.stop()

    def update_elapsed_time(self):
        elapsed = self.start_time.secsTo(QTime.currentTime())
        elapsed_time_str = QTime(0, 0).addSecs(elapsed).toString("hh:mm:ss")
        self.elapsed_time_label.setText(f"경과 시간: {elapsed_time_str}")

    def update_progress(self, value):
        self.progress_bar.setValue(value)
