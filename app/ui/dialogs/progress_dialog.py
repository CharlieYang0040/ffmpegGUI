from PySide6.QtCore import QObject, QTime, QTimer, Signal
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout


class ProgressSignals(QObject):
    """Signals for progress updates."""

    progress = Signal(int)
    task = Signal(str)
    error = Signal(str)
    completed = Signal()


class EncodingProgressDialog(QDialog):
    """Dialog that shows long-running setup/encoding progress."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 진행 상황")
        self.setFixedSize(380, 220)

        layout = QVBoxLayout()
        self.status_label = QLabel("처리 중...")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.current_task_label = QLabel("준비 중...")
        self.current_task_label.setWordWrap(True)
        layout.addWidget(self.current_task_label)

        self.elapsed_time_label = QLabel("경과 시간: 00:00:00")
        layout.addWidget(self.elapsed_time_label)

        self.cancel_button = QPushButton("취소")
        self.cancel_button.setEnabled(False)
        if parent is not None and hasattr(parent, "cancel_encoding"):
            self.cancel_button.setEnabled(True)
            self.cancel_button.clicked.connect(parent.cancel_encoding)
        layout.addWidget(self.cancel_button)

        self.setLayout(layout)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed_time)
        self.start_time = QTime()
        self.is_error = False

    def start_timer(self):
        self.start_time = QTime.currentTime()
        self.timer.start(1000)

    def stop_timer(self):
        self.timer.stop()
        self.cancel_button.setEnabled(False)

    def update_elapsed_time(self):
        if not self.is_error:
            elapsed = self.start_time.secsTo(QTime.currentTime())
            elapsed_time_str = QTime(0, 0).addSecs(elapsed).toString("hh:mm:ss")
            self.elapsed_time_label.setText(f"경과 시간: {elapsed_time_str}")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_task(self, task_description):
        self.current_task_label.setText(task_description)

    def show_error(self, error_message):
        self.is_error = True
        self.stop_timer()
        self.status_label.setText("에러 발생")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.current_task_label.setText(error_message)
        self.current_task_label.setStyleSheet("color: red;")
