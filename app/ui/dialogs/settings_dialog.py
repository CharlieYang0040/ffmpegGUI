from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    """Low-frequency application and diagnostic settings."""

    def __init__(self, ffmpeg_path="", debug_enabled=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("FFmpeg 실행 파일"))
        path_row = QHBoxLayout()
        self.ffmpeg_path_edit = QLineEdit(ffmpeg_path)
        browse_button = QPushButton("찾아보기")
        browse_button.clicked.connect(self.browse_ffmpeg)
        path_row.addWidget(self.ffmpeg_path_edit, 1)
        path_row.addWidget(browse_button)
        layout.addLayout(path_row)

        path_help = QLabel(
            "일반적으로 직접 설정할 필요가 없습니다. 앱이 처음 실행될 때 자동으로 준비합니다."
        )
        path_help.setWordWrap(True)
        path_help.setProperty("role", "muted")
        layout.addWidget(path_help)

        self.debug_checkbox = QCheckBox("진단 로그 자세히 기록")
        self.debug_checkbox.setChecked(debug_enabled)
        layout.addWidget(self.debug_checkbox)

        update_button = QPushButton("업데이트 확인")
        update_button.clicked.connect(self.request_update)
        layout.addWidget(update_button)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_button = QPushButton("취소")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("저장")
        save_button.setProperty("role", "primary")
        save_button.clicked.connect(self.accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

    def browse_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "FFmpeg 실행 파일 선택",
            self.ffmpeg_path_edit.text(),
            "FFmpeg (ffmpeg.exe);;모든 파일 (*.*)",
        )
        if path:
            self.ffmpeg_path_edit.setText(path)

    def request_update(self):
        parent = self.parent()
        update_checker = getattr(parent, "update_checker", None)
        if update_checker:
            update_checker.check_for_updates()
