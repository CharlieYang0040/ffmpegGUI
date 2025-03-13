import os
import logging
from typing import Optional, Tuple, Dict, List
from PySide6.QtWidgets import (
    QWidget, QSlider, QHBoxLayout, QVBoxLayout, QLabel, 
    QPushButton, QFrame, QSpinBox, QStyle, QSizePolicy, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QSize, QPoint, QRect, QEvent
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QMouseEvent, QPaintEvent, QFont, QShortcut, QKeySequence

from app.services.logging_service import LoggingService
from app.core.commands import SetInPointCommand, SetOutPointCommand, SeekFrameCommand
from app.core.events import event_emitter, Events

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

class TimelineMarker(QWidget):
    """타임라인 마커 위젯"""
    
    # 마커 이동 시그널
    marker_moved = Signal(int)  # 마커 위치(프레임)
    
    def __init__(self, parent=None, marker_type="current"):
        """
        타임라인 마커 초기화
        
        Args:
            parent: 부모 위젯
            marker_type: 마커 유형 ("current", "in", "out")
        """
        super().__init__(parent)
        self.marker_type = marker_type
        self.setFixedSize(10, 20)
        
        # 마커 색상 설정
        self.colors = {
            "current": QColor(255, 255, 255),  # 현재 프레임 마커 (흰색)
            "in": QColor(0, 255, 0),           # 시작 프레임 마커 (녹색)
            "out": QColor(255, 0, 0)           # 종료 프레임 마커 (빨간색)
        }
        
        # 마우스 드래그 관련 변수
        self.dragging = False
        self.drag_start_pos = QPoint()
        
        # 마커 위치 설정
        self.frame_position = 1  # 1부터 시작
        
        # 마커 툴팁 설정
        self.setToolTip(self._get_tooltip_text())
        
        # 마우스 추적 활성화
        self.setMouseTracking(True)
        
        # 마커를 항상 위에 표시
        self.raise_()
    
    def _get_tooltip_text(self) -> str:
        """마커 유형에 따른 툴팁 텍스트 반환"""
        if self.marker_type == "current":
            return "현재 프레임"
        elif self.marker_type == "in":
            return "시작 프레임"
        elif self.marker_type == "out":
            return "종료 프레임"
        return ""
    
    def paintEvent(self, event: QPaintEvent):
        """마커 그리기"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 마커 색상 설정
        color = self.colors.get(self.marker_type, QColor(255, 255, 255))
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(Qt.black, 1))
        
        # 마커 모양 그리기
        if self.marker_type == "current":
            # 현재 프레임 마커 (삼각형)
            points = [
                QPoint(5, 0),
                QPoint(10, 10),
                QPoint(0, 10)
            ]
            painter.drawPolygon(points)
            
            # 현재 프레임 마커 선
            painter.setPen(QPen(color, 1))
            painter.drawLine(5, 10, 5, 20)
        elif self.marker_type == "in":
            # 시작 프레임 마커 ([ 모양)
            painter.setPen(QPen(color, 2))
            painter.drawLine(0, 0, 0, 20)  # 왼쪽 세로선
            painter.drawLine(0, 0, 5, 0)   # 위쪽 가로선
            painter.drawLine(0, 20, 5, 20) # 아래쪽 가로선
        elif self.marker_type == "out":
            # 종료 프레임 마커 (] 모양)
            painter.setPen(QPen(color, 2))
            painter.drawLine(10, 0, 10, 20)  # 오른쪽 세로선
            painter.drawLine(5, 0, 10, 0)    # 위쪽 가로선
            painter.drawLine(5, 20, 10, 20)  # 아래쪽 가로선
    
    def mousePressEvent(self, event: QMouseEvent):
        """마우스 클릭 이벤트 처리"""
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """마우스 이동 이벤트 처리"""
        if self.dragging:
            # 부모 타임라인에 마커 이동 요청
            delta_x = event.pos().x() - self.drag_start_pos.x()
            new_pos = self.pos() + QPoint(delta_x, 0)
            
            # 부모 타임라인 내에서만 이동 가능하도록 제한
            if self.parent():
                timeline_width = self.parent().width() - self.width()
                new_x = max(0, min(new_pos.x(), timeline_width))
                new_pos.setX(new_x)
                
                # 프레임 위치 계산 (1부터 시작)
                frame_position = int((new_x / timeline_width) * (self.parent().frame_count - 1)) + 1
                if frame_position != self.frame_position:
                    self.frame_position = frame_position
                    # 마커 이동 시그널 발생
                    self.marker_moved.emit(frame_position)
                
                # 위젯 위치 업데이트
                self.move(new_pos)
                
                # 마커를 항상 위에 표시
                self.raise_()
        else:
            self.setCursor(Qt.OpenHandCursor)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """마우스 릴리즈 이벤트 처리"""
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            self.setCursor(Qt.ArrowCursor)
    
    def set_frame_position(self, frame: int):
        """프레임 위치 설정"""
        self.frame_position = frame
        
        # 부모 타임라인 내에서만 위치 계산
        if self.parent() and self.parent().frame_count > 0:
            timeline_width = self.parent().width() - self.width()
            position_ratio = frame / self.parent().frame_count
            new_x = int(position_ratio * timeline_width)
            
            # 현재 위치와 다른 경우에만 이동
            if self.x() != new_x:
                self.move(new_x, self.y())
                logger.debug(f"{self.marker_type} 마커 위치 설정: 프레임 {frame}, 위치 {new_x}")
                
                # 마커를 항상 위에 표시
                self.raise_()


class TimelineWidget(QWidget):
    """타임라인 위젯"""
    
    # 시그널 정의
    frame_changed = Signal(int)  # 현재 프레임 변경
    in_point_changed = Signal(int)  # 시작 프레임 변경
    out_point_changed = Signal(int)  # 종료 프레임 변경
    playback_requested = Signal()  # 재생 요청
    
    def __init__(self, parent=None):
        """타임라인 위젯 초기화"""
        super().__init__(parent)
        
        # 타임라인 속성
        self.frame_count = 0
        self.current_frame = 1  # 1부터 시작
        self.in_point = 1       # 1부터 시작
        self.out_point = 1      # 1부터 시작
        self.fps = 30
        self.duration = 0
        
        # 마우스 드래그 관련 변수
        self.dragging = False
        self.drag_start_pos = QPoint()
        
        # 위젯 설정
        self.setMinimumHeight(80)  # 높이 증가
        self.setFixedHeight(80)
        self.setMouseTracking(True)
        
        # 마커 생성
        self.current_marker = TimelineMarker(self, "current")
        self.in_marker = TimelineMarker(self, "in")
        self.out_marker = TimelineMarker(self, "out")
        
        # 마커 시그널 연결
        self.current_marker.marker_moved.connect(self._on_current_marker_moved)
        self.in_marker.marker_moved.connect(self._on_in_marker_moved)
        self.out_marker.marker_moved.connect(self._on_out_marker_moved)
        
        # 마커 초기 위치 설정
        self.current_marker.move(0, 25)  # 마커 위치 조정
        self.in_marker.move(0, 50)
        self.out_marker.move(10, 50)
        
        # 마커 표시 여부
        self.show_in_out_markers = True
        
        # 타임코드 표시 설정
        self.show_timecode = True
        self.timecode_font = QFont("Monospace", 8)
        
        # 프레임 눈금 표시 설정
        self.show_frame_ticks = True
        self.major_tick_interval = 10  # 주요 눈금 간격 (프레임)
        self.minor_tick_interval = 1   # 보조 눈금 간격 (프레임)
        
        # 프레임 숫자 표시 설정
        self.show_frame_numbers = True
        self.frame_number_font = QFont("Monospace", 7)
    
    def set_video_info(self, frame_count: int, fps: float, duration: float, nb_frames: int = 0):
        """비디오 정보 설정"""
        logger.debug(f"타임라인 위젯에 비디오 정보 설정: {frame_count} 프레임, {fps} fps, {duration} 초, nb_frames: {nb_frames}")
        
        # 이전 값 저장
        old_frame_count = self.frame_count
        
        # nb_frames가 유효하면 우선 사용
        if nb_frames > 0:
            logger.debug(f"nb_frames 정보 사용: {nb_frames}프레임")
            frame_count = nb_frames
        elif frame_count <= 0 and duration > 0 and fps > 0:
            # frame_count가 없는 경우 duration * fps 사용
            frame_count = int(duration * fps)
            logger.warning(f"frame_count와 nb_frames 정보가 없어 duration * fps로 계산: {duration} * {fps} = {frame_count}")
        
        # 새 값 설정
        self.frame_count = frame_count
        self.fps = fps
        self.duration = duration
        
        # 종료 프레임 설정 (프레임 수가 변경된 경우)
        if old_frame_count != frame_count:
            self.out_point = frame_count  # 1부터 시작하므로 frame_count가 마지막 프레임
            
            # 시작 프레임이 1보다 작으면 1로 설정
            if self.in_point < 1:
                self.in_point = 1
                
            # 현재 프레임이 1보다 작으면 1로 설정
            if self.current_frame < 1:
                self.current_frame = 1
        
        # 마커 위치 업데이트
        self._update_marker_positions()
        
        # 위젯 업데이트
        self.update()
        
        logger.debug(f"타임라인 위젯 비디오 정보 설정 완료: {self.frame_count} 프레임")
    
    def set_current_frame(self, frame: int):
        """현재 프레임 설정"""
        if 1 <= frame <= self.frame_count:  # 1부터 시작
            self.current_frame = frame
            self.current_marker.set_frame_position(frame)
            self.update()
    
    def set_in_point(self, frame: int):
        """시작 프레임 설정"""
        if 1 <= frame <= self.out_point:  # 1부터 시작
            self.in_point = frame
            self.in_marker.set_frame_position(frame)
            self.update()
            self.in_point_changed.emit(frame)
    
    def set_out_point(self, frame: int):
        """종료 프레임 설정"""
        if self.in_point <= frame <= self.frame_count:  # 1부터 시작, 마지막 프레임은 frame_count
            self.out_point = frame
            self.out_marker.set_frame_position(frame)
            self.update()
            self.out_point_changed.emit(frame)
    
    def toggle_in_out_markers(self, show: bool):
        """시작/종료 마커 표시 여부 설정"""
        self.show_in_out_markers = show
        self.in_marker.setVisible(show)
        self.out_marker.setVisible(show)
        self.update()
    
    def _update_marker_positions(self):
        """마커 위치 업데이트"""
        if self.frame_count <= 0:
            return
            
        timeline_width = self.width() - self.current_marker.width()
        
        # 현재 프레임 마커 위치 설정 (1부터 시작하므로 -1 보정)
        current_x = int(((self.current_frame - 1) / (self.frame_count - 1)) * timeline_width) if self.frame_count > 1 else 0
        self.current_marker.move(current_x, 25)  # 마커 위치 조정
        
        # 시작 프레임 마커 위치 설정 (1부터 시작하므로 -1 보정)
        in_x = int(((self.in_point - 1) / (self.frame_count - 1)) * timeline_width) if self.frame_count > 1 else 0
        self.in_marker.move(in_x, 50)  # 마커 위치 조정
        
        # 종료 프레임 마커 위치 설정 (1부터 시작하므로 -1 보정)
        out_x = int(((self.out_point - 1) / (self.frame_count - 1)) * timeline_width) if self.frame_count > 1 else 0
        self.out_marker.move(out_x, 50)  # 마커 위치 조정
        
        # 마커를 항상 위에 표시
        self.current_marker.raise_()
        self.in_marker.raise_()
        self.out_marker.raise_()
        
        # 로깅
        logger.debug(f"마커 위치 업데이트: 현재={self.current_frame}({current_x}), 시작={self.in_point}({in_x}), 종료={self.out_point}({out_x})")
    
    def _on_current_marker_moved(self, frame: int):
        """현재 프레임 마커 이동 처리"""
        if 1 <= frame <= self.frame_count:  # 1부터 시작
            self.current_frame = frame
            self.frame_changed.emit(frame)
    
    def _on_in_marker_moved(self, frame: int):
        """시작 프레임 마커 이동 처리"""
        if 1 <= frame <= self.out_point:  # 1부터 시작
            self.in_point = frame
            self.in_point_changed.emit(frame)
    
    def _on_out_marker_moved(self, frame: int):
        """종료 프레임 마커 이동 처리"""
        if self.in_point <= frame <= self.frame_count:  # 1부터 시작, 마지막 프레임은 frame_count
            self.out_point = frame
            self.out_point_changed.emit(frame)
    
    def paintEvent(self, event: QPaintEvent):
        """타임라인 그리기"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 타임라인 배경 그리기
        painter.fillRect(self.rect(), QColor(40, 40, 40))
        
        # 프레임이 없으면 그리기 중단
        if self.frame_count <= 0:
            painter.setPen(QPen(QColor(150, 150, 150), 1))
            painter.drawText(self.rect(), Qt.AlignCenter, "비디오 정보 없음")
            return
        
        # 타임라인 영역 계산
        timeline_rect = QRect(0, 25, self.width(), 20)  # 타임라인 위치 조정
        
        # 시작/종료 구간 표시
        if self.show_in_out_markers and self.in_point < self.out_point:
            in_pos = (self.in_point / self.frame_count) * self.width()
            out_pos = (self.out_point / self.frame_count) * self.width()
            selection_rect = QRect(int(in_pos), 25, int(out_pos - in_pos), 20)  # 구간 위치 조정
            painter.fillRect(selection_rect, QColor(0, 120, 215, 100))
            
            # 구간 경계선 그리기
            painter.setPen(QPen(QColor(0, 120, 215), 1))
            painter.drawLine(int(in_pos), 25, int(in_pos), 45)
            painter.drawLine(int(out_pos), 25, int(out_pos), 45)
        
        # 프레임 눈금 그리기
        if self.show_frame_ticks and self.frame_count > 0:
            painter.setPen(QPen(QColor(150, 150, 150), 1))
            
            # 주요 눈금 간격 계산 (프레임 수에 따라 자동 조정)
            if self.frame_count > 1000:
                self.major_tick_interval = max(100, self.frame_count // 20)
            elif self.frame_count > 500:
                self.major_tick_interval = max(50, self.frame_count // 20)
            elif self.frame_count > 100:
                self.major_tick_interval = max(20, self.frame_count // 20)
            else:
                self.major_tick_interval = max(10, self.frame_count // 10)
            
            # 주요 눈금 그리기
            for frame in range(0, self.frame_count + 1, self.major_tick_interval):
                x_pos = int((frame / self.frame_count) * self.width())
                painter.drawLine(x_pos, 45, x_pos, 50)  # 눈금 위치 조정
                
                # 타임코드 표시
                if self.show_timecode:
                    time_sec = frame / self.fps
                    seconds = int(time_sec % 60)
                    frames = int((time_sec % 1) * self.fps)
                    timecode = f"{seconds:02d}"
                    
                    painter.setFont(self.timecode_font)
                    painter.drawText(x_pos - 20, 60, 40, 15, Qt.AlignCenter, timecode)  # 타임코드 위치 조정
                
                # 프레임 숫자 표시
                if self.show_frame_numbers:
                    painter.setFont(self.frame_number_font)
                    painter.drawText(x_pos - 15, 5, 30, 15, Qt.AlignCenter, str(frame))  # 프레임 숫자 위치
            
            # 보조 눈금 그리기 (주요 눈금 사이에 보조 눈금)
            minor_interval = max(1, self.major_tick_interval // 5)
            if minor_interval > 0 and self.frame_count <= 500:  # 프레임이 많을 때는 보조 눈금 생략
                for frame in range(0, self.frame_count + 1):
                    if frame % self.major_tick_interval != 0 and frame % minor_interval == 0:
                        x_pos = int((frame / self.frame_count) * self.width())
                        painter.drawLine(x_pos, 45, x_pos, 48)  # 보조 눈금 위치 조정
        
        # 현재 프레임 위치 선 그리기
        current_pos = int((self.current_frame / self.frame_count) * self.width())
        painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
        painter.drawLine(current_pos, 0, current_pos, self.height())
        
        # 디버그 정보 표시
        debug_info = f"프레임: {self.current_frame}/{self.frame_count} (FPS: {self.fps:.1f})"
        painter.setPen(QPen(QColor(200, 200, 200), 1))
        painter.drawText(5, self.height() - 20, debug_info)  # 위치를 아래로 조정 (-5 → -10)
    
    def mousePressEvent(self, event: QMouseEvent):
        """마우스 클릭 이벤트 처리"""
        if event.button() == Qt.LeftButton and 25 <= event.y() < 45:  # 클릭 영역 조정
            self.dragging = True
            self.drag_start_pos = event.pos()
            
            # 클릭 위치의 프레임 계산 (1부터 시작)
            frame_position = int((event.x() / self.width()) * (self.frame_count - 1)) + 1
            frame_position = max(1, min(frame_position, self.frame_count))
            
            # 현재 프레임 업데이트
            self.set_current_frame(frame_position)
            self.frame_changed.emit(frame_position)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """마우스 이동 이벤트 처리"""
        if self.dragging and event.buttons() & Qt.LeftButton:
            # 드래그 위치의 프레임 계산 (1부터 시작)
            frame_position = int((event.x() / self.width()) * (self.frame_count - 1)) + 1
            frame_position = max(1, min(frame_position, self.frame_count))
            
            # 현재 프레임 업데이트
            self.set_current_frame(frame_position)
            self.frame_changed.emit(frame_position)
        
        # 마우스 위치의 프레임/시간 정보 툴팁 표시
        if 0 <= event.x() <= self.width() and self.frame_count > 0:
            # 프레임 위치 계산 (1부터 시작)
            frame_position = int((event.x() / self.width()) * (self.frame_count - 1)) + 1
            frame_position = max(1, min(frame_position, self.frame_count))
            
            time_sec = (frame_position - 1) / self.fps  # 시간 계산 시 0부터 시작하는 인덱스로 변환
            minutes = int(time_sec // 60)
            seconds = int(time_sec % 60)
            frames = int((time_sec % 1) * self.fps)
            
            tooltip = f"프레임: {frame_position} / {self.frame_count}\n시간: {minutes:02d}:{seconds:02d}:{frames:02d}"
            self.setToolTip(tooltip)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """마우스 릴리즈 이벤트 처리"""
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
    
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """마우스 더블 클릭 이벤트 처리"""
        if event.button() == Qt.LeftButton:
            # 더블 클릭 시 재생 요청
            self.playback_requested.emit()
    
    def resizeEvent(self, event):
        """위젯 크기 변경 이벤트 처리"""
        super().resizeEvent(event)
        
        # 마커 위치 업데이트
        self._update_marker_positions()
        
        # 로깅
        logger.debug(f"타임라인 크기 변경: {self.width()}x{self.height()}")


class TimelineComponent:
    """타임라인 컴포넌트 클래스"""
    
    def __init__(self, parent):
        """
        타임라인 컴포넌트 초기화
        
        Args:
            parent: 부모 위젯 (FFmpegGui 인스턴스)
        """
        self.parent = parent
        self.timeline_widget = None
        self.frame_spinbox = None
        self.in_point_spinbox = None
        self.out_point_spinbox = None
        self.duration_label = None
        self.play_button = None
        self.speed_slider = None
        self.speed_value_label = None
        self.apply_trim_button = None
    
    def create_timeline_area(self, layout):
        """타임라인 영역 생성"""
        # 타임라인 컨테이너 프레임
        timeline_frame = QFrame()
        timeline_frame.setFrameShape(QFrame.StyledPanel)
        # timeline_frame.setStyleSheet("background-color: #2a2a2a; border: 1px solid #3a3a3a;")
        timeline_frame.setFixedHeight(130)
        
        # 타임라인 레이아웃
        timeline_layout = QVBoxLayout(timeline_frame)
        timeline_layout.setContentsMargins(5, 5, 5, 5)
        
        # 재생 컨트롤 레이아웃 생성
        self._create_playback_controls(timeline_layout)
        
        # 타임라인 위젯 생성
        self.timeline_widget = TimelineWidget()
        self.timeline_widget.frame_changed.connect(self._on_frame_changed)
        self.timeline_widget.in_point_changed.connect(self._on_in_point_changed)
        self.timeline_widget.out_point_changed.connect(self._on_out_point_changed)
        self.timeline_widget.playback_requested.connect(self._on_playback_requested)
        
        # 타임라인 레이아웃에 위젯 추가
        timeline_layout.addWidget(self.timeline_widget)
        
        # 메인 레이아웃에 타임라인 프레임 추가
        layout.addWidget(timeline_frame)
        
        # 프레임 컨트롤 영역은 더 이상 여기서 생성하지 않음
        # self._create_frame_controls(layout)
    
    def _create_playback_controls(self, layout):
        """재생 컨트롤 생성"""
        # 재생 컨트롤 레이아웃
        playback_layout = QHBoxLayout()
        
        # 재생/정지 버튼
        self.play_button = QPushButton("▶️ 재생")
        self.play_button.clicked.connect(self._on_play_button_clicked)
        self.play_button.setEnabled(False)
        self.parent.play_button = self.play_button  # 부모 위젯에 참조 설정
        playback_layout.addWidget(self.play_button)
        
        # 속도 조절 레이아웃
        speed_layout = QHBoxLayout()
        
        # "재생 속도:" 레이블 - 높이 고정
        speed_label = QLabel("재생 속도:")
        speed_label.setFixedHeight(20)  # 높이를 20픽셀로 고정
        speed_layout.addWidget(speed_label)
        
        # 속도 조절 슬라이더
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(10, 400)  # 0.1x ~ 4.0x로 확장
        self.speed_slider.setValue(100)      # 기본값 1.0x
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(50)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.parent.speed_slider = self.speed_slider  # 부모 위젯에 참조 설정
        speed_layout.addWidget(self.speed_slider)
        
        # 속도 표시 레이블 - 높이 고정
        self.speed_value_label = QLabel("1.0x")
        self.speed_value_label.setFixedHeight(20)  # 높이를 20픽셀로 고정
        self.speed_value_label.setMinimumWidth(40)  # 최소 너비 설정으로 텍스트가 잘리지 않도록
        self.parent.speed_value_label = self.speed_value_label  # 부모 위젯에 참조 설정
        speed_layout.addWidget(self.speed_value_label)
        
        # 재생 컨트롤 레이아웃에 속도 레이아웃 추가
        playback_layout.addLayout(speed_layout)
        playback_layout.addStretch()
        
        # 메인 레이아웃에 재생 컨트롤 추가
        layout.addLayout(playback_layout)
    
    def create_frame_controls(self, layout):
        """프레임 컨트롤 영역 생성 (외부에서 호출 가능)"""
        self._create_frame_controls(layout)
    
    def _create_frame_controls(self, layout):
        """프레임 컨트롤 영역 생성 (별도의 그룹박스로 분리)"""
        # 프레임 컨트롤 그룹박스
        frame_control_group = QGroupBox("프레임 컨트롤")
        # frame_control_group.setStyleSheet("background-color: #2a2a2a; border: 1px solid #3a3a3a;")
        frame_control_layout = QVBoxLayout(frame_control_group)
        
        # 프레임 컨트롤 상단 레이아웃 (현재 프레임)
        top_layout = QHBoxLayout()
        top_layout.setSpacing(15)
        
        # 현재 프레임 컨트롤
        frame_layout = QHBoxLayout()
        frame_layout.addWidget(QLabel("현재 프레임:"))
        self.frame_spinbox = QSpinBox()
        self.frame_spinbox.setMinimum(1)  # 1부터 시작
        self.frame_spinbox.setMaximum(1)  # 초기값 1
        self.frame_spinbox.setMinimumWidth(80)
        self.frame_spinbox.valueChanged.connect(self._on_frame_spinbox_changed)
        frame_layout.addWidget(self.frame_spinbox)
        
        top_layout.addLayout(frame_layout)
        top_layout.addStretch()
        
        # 프레임 컨트롤 중간 레이아웃 (시작/종료 프레임)
        middle_layout = QHBoxLayout()
        middle_layout.setSpacing(15)
        
        # 시작 프레임 컨트롤
        in_layout = QHBoxLayout()
        in_layout.addWidget(QLabel("시작 프레임:"))
        self.in_point_spinbox = QSpinBox()
        self.in_point_spinbox.setMinimum(1)  # 1부터 시작
        self.in_point_spinbox.setMaximum(1)  # 초기값 1
        self.in_point_spinbox.setMinimumWidth(80)
        self.in_point_spinbox.valueChanged.connect(self._on_in_spinbox_changed)
        in_layout.addWidget(self.in_point_spinbox)
        
        # 종료 프레임 컨트롤
        out_layout = QHBoxLayout()
        out_layout.addWidget(QLabel("종료 프레임:"))
        self.out_point_spinbox = QSpinBox()
        self.out_point_spinbox.setMinimum(1)  # 1부터 시작
        self.out_point_spinbox.setMaximum(1)  # 초기값 1
        self.out_point_spinbox.setMinimumWidth(80)
        self.out_point_spinbox.valueChanged.connect(self._on_out_spinbox_changed)
        out_layout.addWidget(self.out_point_spinbox)
        
        middle_layout.addLayout(in_layout)
        middle_layout.addLayout(out_layout)
        middle_layout.addStretch()
        
        # 프레임 컨트롤 하단 레이아웃 (구간 정보 및 적용 버튼)
        bottom_layout = QHBoxLayout()
        
        # 구간 정보 레이블
        self.duration_label = QLabel("구간: 00:00:00 (0 프레임)")
        self.duration_label.setMinimumWidth(180)
        
        # 적용 버튼
        self.apply_trim_button = QPushButton("트림 적용")
        self.apply_trim_button.clicked.connect(self._on_apply_trim_clicked)
        
        bottom_layout.addWidget(self.duration_label)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.apply_trim_button)
        
        # 프레임 컨트롤 레이아웃에 위젯 추가
        frame_control_layout.addLayout(top_layout)
        frame_control_layout.addLayout(middle_layout)
        frame_control_layout.addLayout(bottom_layout)
        
        # 메인 레이아웃에 프레임 컨트롤 그룹박스 추가
        layout.addWidget(frame_control_group)
    
    def set_video_info(self, frame_count: int, fps: float, duration: float, nb_frames: int = 0):
        """비디오 정보 설정"""
        logger.debug(f"타임라인 컴포넌트에 비디오 정보 설정: {frame_count} 프레임, {fps} fps, {duration} 초, nb_frames: {nb_frames}")
        
        # 유효하지 않은 값 확인 및 기본값 설정
        if frame_count <= 0 and nb_frames <= 0:
            logger.warning("유효하지 않은 프레임 수, 기본값 사용")
            frame_count = 300
        elif nb_frames > 0:
            # nb_frames가 유효하면 우선 사용
            logger.debug(f"nb_frames 정보 사용: {nb_frames}프레임")
            frame_count = nb_frames
        
        if fps <= 0:
            logger.warning("유효하지 않은 FPS, 기본값 사용")
            fps = 30
            
        if duration <= 0:
            logger.warning("유효하지 않은 재생 시간, 기본값 사용")
            duration = frame_count / fps
        
        if self.timeline_widget:
            # 타임라인 위젯에 비디오 정보 설정
            self.timeline_widget.set_video_info(frame_count, fps, duration, nb_frames)
            
            # 스핀박스 범위 설정
            self.frame_spinbox.setMinimum(1)  # 1부터 시작
            self.frame_spinbox.setMaximum(frame_count)  # 마지막 프레임은 frame_count
            self.in_point_spinbox.setMinimum(1)  # 1부터 시작
            self.in_point_spinbox.setMaximum(frame_count)  # 마지막 프레임은 frame_count
            self.out_point_spinbox.setMinimum(1)  # 1부터 시작
            self.out_point_spinbox.setMaximum(frame_count)  # 마지막 프레임은 frame_count
            self.out_point_spinbox.setValue(frame_count)  # 마지막 프레임은 frame_count
            
            # 구간 정보 업데이트
            self._update_duration_info()
            
            # 재생 버튼 활성화
            if self.play_button:
                self.play_button.setEnabled(True)
    
    def set_current_frame(self, frame: int):
        """현재 프레임 설정"""
        if self.timeline_widget:
            self.timeline_widget.set_current_frame(frame)
            self.frame_spinbox.setValue(frame)
    
    def get_in_point(self) -> int:
        """시작 프레임 반환"""
        return self.timeline_widget.in_point if self.timeline_widget else 0
    
    def get_out_point(self) -> int:
        """종료 프레임 반환"""
        return self.timeline_widget.out_point if self.timeline_widget else 0
    
    def _on_frame_changed(self, frame: int):
        """프레임 변경 이벤트 처리"""
        # 스핀박스 값만 업데이트하고 비디오 스레드에 직접 요청하지 않음
        # 이벤트 루프 충돌 방지
        if self.frame_spinbox.value() != frame:
            self.frame_spinbox.setValue(frame)
    
    def _on_in_point_changed(self, frame: int):
        """시작 프레임 변경 이벤트 처리"""
        self.in_point_spinbox.setValue(frame)
        self._update_duration_info()

    def _on_out_point_changed(self, frame: int):
        """종료 프레임 변경 이벤트 처리"""
        self.out_point_spinbox.setValue(frame)
        self._update_duration_info()
    
    def _on_out_spinbox_changed(self, value: int):
        """종료 프레임 스핀박스 변경 이벤트 처리"""
        if self.timeline_widget and self.timeline_widget.out_point != value:
            # 현재 종료 프레임 저장
            old_out_point = self.timeline_widget.out_point
            
            # 명령 패턴 활용 - 종료 프레임 설정 명령 생성 및 실행
            from app.core.commands import SetOutPointCommand, command_manager
            
            # 명령 생성 및 실행
            out_point_command = SetOutPointCommand(
                self.timeline_widget,
                old_out_point,
                value
            )
            command_manager.execute(out_point_command)
    
    def _on_frame_spinbox_changed(self, value: int):
        """프레임 스핀박스 변경 이벤트 처리"""
        if self.timeline_widget and self.timeline_widget.current_frame != value:
            # 현재 프레임 저장
            old_frame = self.timeline_widget.current_frame
            
            # 타임라인 위젯 업데이트
            self.timeline_widget.set_current_frame(value)
            
            # 명령 패턴 활용 - 프레임 이동 명령 생성 및 실행
            from app.core.commands import SeekFrameCommand, command_manager
            
            # 비디오 스레드 참조 가져오기
            video_thread = None
            if hasattr(self.parent, 'preview_area') and self.parent.preview_area.video_thread:
                video_thread = self.parent.preview_area.video_thread
            
            # 명령 생성 및 실행
            seek_command = SeekFrameCommand(
                self.timeline_widget, 
                old_frame, 
                value, 
                video_thread
            )
            command_manager.execute(seek_command)
    
    def _on_in_spinbox_changed(self, value: int):
        """시작 프레임 스핀박스 변경 이벤트 처리"""
        if self.timeline_widget and self.timeline_widget.in_point != value:
            # 현재 시작 프레임 저장
            old_in_point = self.timeline_widget.in_point
            
            # 명령 패턴 활용 - 시작 프레임 설정 명령 생성 및 실행
            from app.core.commands import SetInPointCommand, command_manager
            
            # 명령 생성 및 실행
            in_point_command = SetInPointCommand(
                self.timeline_widget,
                old_in_point,
                value
            )
            command_manager.execute(in_point_command)
    
    def _on_playback_requested(self):
        """재생 요청 이벤트 처리"""
        if hasattr(self.parent, 'preview_area'):
            self.parent.preview_area.toggle_play()
    
    def _on_play_button_clicked(self):
        """재생 버튼 클릭 이벤트 처리"""
        if hasattr(self.parent, 'preview_area'):
            self.parent.preview_area.toggle_play()
    
    def _on_speed_changed(self, value):
        """재생 속도 변경 이벤트 처리"""
        speed = value / 100.0
        self.speed_value_label.setText(f"{speed:.1f}x")
        
        if hasattr(self.parent, 'preview_area'):
            self.parent.preview_area.change_speed()
    
    def _update_duration_info(self):
        """구간 정보 업데이트"""
        if not self.timeline_widget:
            return
        
        in_point = self.timeline_widget.in_point
        out_point = self.timeline_widget.out_point
        fps = self.timeline_widget.fps
        
        # 프레임 수 계산
        frame_count = out_point - in_point + 1
        
        # 시간 계산
        duration_sec = frame_count / fps
        minutes = int(duration_sec // 60)
        seconds = int(duration_sec % 60)
        frames = int((duration_sec % 1) * fps)
        
        # 구간 정보 업데이트
        self.duration_label.setText(f"구간: {minutes:02d}:{seconds:02d}:{frames:02d} ({frame_count} 프레임)")
    
    def _on_apply_trim_clicked(self):
        """트림 적용 버튼 클릭 이벤트 처리"""
        # 현재 선택된 아이템이 있는지 확인
        if not hasattr(self.parent, 'list_widget') or not self.parent.list_widget.currentItem():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.parent, "경고", "트림을 적용할 아이템을 선택해주세요.")
            return
        
        # 시작/종료 프레임 가져오기
        in_point = self.get_in_point()
        out_point = self.get_out_point()
        
        # 비디오 정보 가져오기
        if hasattr(self.parent, 'preview_area') and self.parent.preview_area.video_thread:
            video_info = self.parent.preview_area.video_thread.get_video_info()
            frame_count = video_info.get('frame_count', 0)
            
            # 프레임 단위로 트림 값 설정
            start_frame = in_point - 1 # 시작 프레임 (앞에서부터)
            
            # 뒤에서부터 트림할 프레임 수 계산
            # 종료 프레임이 마지막 프레임보다 작으면, 그 차이만큼 뒤에서 트림
            end_trim = frame_count - out_point
            
            # 현재 선택된 아이템에 트림 값 설정
            current_item = self.parent.list_widget.currentItem()
            item_widget = self.parent.list_widget.itemWidget(current_item)
            
            if hasattr(item_widget, 'set_trim_values'):
                item_widget.set_trim_values(start_frame, end_trim)
                logger.info(f"트림 적용: 시작 프레임 {start_frame}, 뒤에서 {end_trim} 프레임 트림 (총 프레임 수: {frame_count})")
                
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self.parent, "알림", f"트림이 적용되었습니다.\n시작 프레임: {start_frame}f\n뒤에서 트림: {end_trim}f\n(총 프레임 수: {frame_count})")
            else:
                logger.warning("아이템 위젯에 set_trim_values 메서드가 없습니다.")
        else:
            logger.warning("비디오 정보를 가져올 수 없습니다.")

    def setup_shortcuts(self):
        """타임라인 관련 단축키 설정"""
        # 'i' 키: 현재 프레임을 시작 프레임으로 설정
        self.in_point_shortcut = QShortcut(QKeySequence("i"), self.parent)
        self.in_point_shortcut.activated.connect(self.set_current_as_in_point)
        
        # 'o' 키: 현재 프레임을 종료 프레임으로 설정
        self.out_point_shortcut = QShortcut(QKeySequence("o"), self.parent)
        self.out_point_shortcut.activated.connect(self.set_current_as_out_point)
        
        # 스페이스바: 재생/정지 토글
        self.play_shortcut = QShortcut(QKeySequence("Space"), self.parent)
        self.play_shortcut.activated.connect(self._on_play_button_clicked)
        
        # 왼쪽 화살표: 이전 프레임
        self.prev_frame_shortcut = QShortcut(QKeySequence("Left"), self.parent)
        self.prev_frame_shortcut.activated.connect(self.seek_prev_frame)
        
        # 오른쪽 화살표: 다음 프레임
        self.next_frame_shortcut = QShortcut(QKeySequence("Right"), self.parent)
        self.next_frame_shortcut.activated.connect(self.seek_next_frame)
        
        # Home 키: 첫 프레임으로 이동
        self.seek_start_shortcut = QShortcut(QKeySequence("Home"), self.parent)
        self.seek_start_shortcut.activated.connect(self.seek_to_start)
        
        # End 키: 마지막 프레임으로 이동
        self.seek_end_shortcut = QShortcut(QKeySequence("End"), self.parent)
        self.seek_end_shortcut.activated.connect(self.seek_to_end)
    
    def set_current_as_in_point(self):
        """현재 프레임을 시작 프레임으로 설정"""
        if not self.timeline_widget:
            return
            
        current_frame = self.timeline_widget.current_frame
        old_in_point = self.timeline_widget.in_point
        
        # 현재 프레임이 종료 프레임보다 크면 설정하지 않음
        if current_frame > self.timeline_widget.out_point:
            logger.warning(f"현재 프레임({current_frame})이 종료 프레임({self.timeline_widget.out_point})보다 큽니다.")
            return
        
        # 명령 실행
        command = SetInPointCommand(self.timeline_widget, old_in_point, current_frame)
        from app.core.commands import command_manager
        command_manager.execute(command)
        
        # 이벤트 발행
        event_emitter.emit(Events.TIMELINE_SET_IN_POINT, current_frame)
        logger.debug(f"시작 프레임을 {current_frame}으로 설정")
    
    def set_current_as_out_point(self):
        """현재 프레임을 종료 프레임으로 설정"""
        if not self.timeline_widget:
            return
            
        current_frame = self.timeline_widget.current_frame
        old_out_point = self.timeline_widget.out_point
        
        # 현재 프레임이 시작 프레임보다 작으면 설정하지 않음
        if current_frame < self.timeline_widget.in_point:
            logger.warning(f"현재 프레임({current_frame})이 시작 프레임({self.timeline_widget.in_point})보다 작습니다.")
            return
        
        # 명령 실행
        command = SetOutPointCommand(self.timeline_widget, old_out_point, current_frame)
        from app.core.commands import command_manager
        command_manager.execute(command)
        
        # 이벤트 발행
        event_emitter.emit(Events.TIMELINE_SET_OUT_POINT, current_frame)
        logger.debug(f"종료 프레임을 {current_frame}으로 설정")
    
    def seek_prev_frame(self):
        """이전 프레임으로 이동"""
        if not self.timeline_widget:
            return
            
        current_frame = self.timeline_widget.current_frame
        if current_frame > 1:
            # 이전 프레임 계산
            prev_frame = current_frame - 1
            
            # 현재 프레임 업데이트 (이벤트 발행은 나중에)
            self.timeline_widget.set_current_frame(prev_frame)
            self.frame_spinbox.setValue(prev_frame)
            
            # 이벤트 발행
            event_emitter.emit(Events.TIMELINE_SEEK_PREV_FRAME, prev_frame)
            logger.debug(f"이전 프레임으로 이동: {prev_frame}")
    
    def seek_next_frame(self):
        """다음 프레임으로 이동"""
        if not self.timeline_widget:
            return
            
        current_frame = self.timeline_widget.current_frame
        if current_frame < self.timeline_widget.frame_count:
            # 다음 프레임 계산
            next_frame = current_frame + 1
            
            # 현재 프레임 업데이트 (이벤트 발행은 나중에)
            self.timeline_widget.set_current_frame(next_frame)
            self.frame_spinbox.setValue(next_frame)
            
            # 이벤트 발행
            event_emitter.emit(Events.TIMELINE_SEEK_NEXT_FRAME, next_frame)
            logger.debug(f"다음 프레임으로 이동: {next_frame}")
    
    def seek_to_start(self):
        """첫 프레임으로 이동"""
        if not self.timeline_widget:
            return
            
        current_frame = self.timeline_widget.current_frame
        
        # 비디오 스레드 가져오기
        video_thread = None
        if hasattr(self.parent, 'preview_area') and hasattr(self.parent.preview_area, 'video_thread'):
            video_thread = self.parent.preview_area.video_thread
        
        # 명령 생성 및 실행
        command = SeekFrameCommand(self.timeline_widget, current_frame, 1, video_thread)
        from app.core.commands import command_manager
        command_manager.execute(command)
        
        # 이벤트 발행
        event_emitter.emit(Events.TIMELINE_SEEK_START, 1)
        logger.debug("첫 프레임으로 이동")
    
    def seek_to_end(self):
        """마지막 프레임으로 이동"""
        if not self.timeline_widget:
            return
            
        current_frame = self.timeline_widget.current_frame
        last_frame = self.timeline_widget.frame_count
        
        # 비디오 스레드 가져오기
        video_thread = None
        if hasattr(self.parent, 'preview_area') and hasattr(self.parent.preview_area, 'video_thread'):
            video_thread = self.parent.preview_area.video_thread
        
        # 명령 생성 및 실행
        command = SeekFrameCommand(self.timeline_widget, current_frame, last_frame, video_thread)
        from app.core.commands import command_manager
        command_manager.execute(command)
        
        # 이벤트 발행
        event_emitter.emit(Events.TIMELINE_SEEK_END, last_frame)
        logger.debug(f"마지막 프레임으로 이동: {last_frame}") 