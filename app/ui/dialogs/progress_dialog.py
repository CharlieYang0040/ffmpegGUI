from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
from PySide6.QtCore import QObject, Signal, QTimer, QTime

class ProgressSignals(QObject):
    """진행률 업데이트를 위한 시그널 클래스"""
    progress = Signal(int)
    task = Signal(str)
    error = Signal(str)
    completed = Signal()

class EncodingProgressDialog(QDialog):
    """
    인코딩 진행 상황을 표시하는 다이얼로그
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 진행 상황")
        self.setFixedSize(350, 180)  # 높이를 늘려서 에러 메시지 표시 공간 확보

        layout = QVBoxLayout()
        
        # 상태 레이블 추가
        self.status_label = QLabel("처리 중...")
        layout.addWidget(self.status_label)
        
        # 진행 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        # 현재 작업 표시 레이블
        self.current_task_label = QLabel("준비 중...")
        layout.addWidget(self.current_task_label)

        # 경과 시간 레이블
        self.elapsed_time_label = QLabel("경과 시간: 00:00:00")
        layout.addWidget(self.elapsed_time_label)

        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed_time)
        self.start_time = QTime()
        self.is_error = False

    def start_timer(self):
        self.start_time = QTime.currentTime()
        self.timer.start(1000)  # 1초마다 업데이트

    def stop_timer(self):
        self.timer.stop()

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
        self.status_label.setText("에러 발생!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.current_task_label.setText(error_message)
        self.current_task_label.setStyleSheet("color: red;")
