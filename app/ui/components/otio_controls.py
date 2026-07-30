import os
import logging
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QLineEdit, QFileDialog, QMessageBox
from PySide6.QtCore import Qt

from app.services.logging_service import LoggingService
from app.utils.utils import is_image_file, process_image_file

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

class OtioControlsComponent:
    """
    OTIO 컨트롤 관련 기능을 제공하는 컴포넌트 클래스
    """
    
    def __init__(self, parent):
        """
        :param parent: 부모 위젯 (FFmpegGui 인스턴스)
        """
        self.parent = parent
    
    def setup_otio_controls(self, layout):
        """OTIO 컨트롤 설정"""
        otio_layout = QHBoxLayout()
        
        self.parent.rv_path_edit = QLineEdit()
        self.parent.rv_path_edit.setPlaceholderText("OpenRV 경로")
        self.parent.rv_path_edit.setText(self.parent.settings_service.get("rv_path", ""))
        
        self.parent.rv_browse_button = QPushButton("RV 찾기")
        self.parent.rv_browse_button.clicked.connect(self.browse_rv_path)
        
        self.parent.create_otio_button = QPushButton("🎬 OTIO 생성 및 열기")
        self.parent.create_otio_button.clicked.connect(self.create_and_open_otio)
        
        self.parent.load_otio_button = QPushButton("📂 OTIO 불러오기")
        self.parent.load_otio_button.clicked.connect(self.load_otio_file)
        
        otio_layout.addWidget(self.parent.rv_path_edit)
        otio_layout.addWidget(self.parent.rv_browse_button)
        otio_layout.addWidget(self.parent.create_otio_button)
        otio_layout.addWidget(self.parent.load_otio_button)
        
        layout.addLayout(otio_layout)
    
    def browse_rv_path(self):
        """OpenRV 경로 선택"""
        rv_path, _ = QFileDialog.getOpenFileName(
            self.parent, 'OpenRV 실행 파일 선택',
            self.parent.rv_path_edit.text(),
            'OpenRV (rv.exe);;모든 파일 (*.*)'
        )
        if rv_path:
            self.parent.rv_path_edit.setText(rv_path)
            self.parent.settings_service.set("rv_path", rv_path)
    
    def create_and_open_otio(self):
        """OTIO 파일 생성 및 열기"""
        if self.parent.list_widget.count() == 0:
            QMessageBox.warning(self.parent, "경고", "파일 목록이 비어있습니다.")
            return
        
        clips = []
        for i in range(self.parent.list_widget.count()):
            item = self.parent.list_widget.item(i)
            item_widget = self.parent.list_widget.itemWidget(item)
            file_path = item_widget.file_path
            trim_start, trim_end = item_widget.get_trim_values()
            clips.append((file_path, trim_start, trim_end))
        
        try:
            from app.utils.otio_utils import generate_and_open_otio
            # 임시 파일로 바로 생성하고 열기
            generate_and_open_otio(clips, None, self.parent.rv_path_edit.text())
        except Exception as e:
            logger.error(f"OTIO 생성 중 오류 발생: {e}")
            QMessageBox.warning(self.parent, "오류", f"OTIO 생성 중 오류가 발생했습니다: {str(e)}")
    
    def load_otio_file(self):
        """OTIO 파일을 선택하고 파싱하여 리스트에 추가"""
        otio_path, _ = QFileDialog.getOpenFileName(
            self.parent, 'OTIO 파일 선택',
            '',
            'OTIO 파일 (*.otio);;모든 파일 (*.*)'
        )
        
        if not otio_path:
            return
        
        try:
            logger.debug(f"OTIO 파일 파싱 시작: {otio_path}")
            from app.utils.otio_utils import parse_otio_file
            clips = parse_otio_file(otio_path)
            logger.debug(f"파싱된 클립 정보: {clips}")
            
            if clips:
                # 기존 리스트 초기화 여부 확인
                if self.parent.list_widget.count() > 0:
                    reply = QMessageBox.question(
                        self.parent,
                        'OTIO 불러오기',
                        '기존 목록을 비우고 OTIO 파일을 불러오시겠습니까?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    
                    if reply == QMessageBox.Yes:
                        self.parent.list_widget.clear()
                
                # 클립 추가
                file_paths = []
                trim_values = {}  # 파일 경로를 키로 하고 (trim_start, trim_end)를 값으로 하는 딕셔너리
                
                for file_path, trim_start, trim_end in clips:
                    logger.debug(f"처리할 파일 정보: 경로={file_path}, 시작={trim_start}, 끝={trim_end}")
                    # 파일 경로 처리
                    file_path = file_path.replace('\\', '/')  # 경로 정규화
                    
                    # 이미지 파일인 경우 시퀀스 처리
                    if is_image_file(file_path):
                        processed_path = process_image_file(file_path)
                        logger.debug(f"이미지 시퀀스 처리 결과: {processed_path}")
                        if processed_path and '%' in processed_path:  # 시퀀스 패턴이 있는 경우
                            file_path = processed_path
                    
                    if os.path.exists(file_path) or '%' in file_path:  # 시퀀스 패턴이 있는 경우도 허용
                        file_paths.append(file_path)
                        trim_values[file_path] = (trim_start, trim_end)
                        logger.debug(f"파일 추가됨: {file_path}")
                    else:
                        logger.warning(f"파일을 찾을 수 없습니다: {file_path}")
                
                if file_paths:
                    # 먼저 파일들을 추가
                    from app.ui.commands.commands import AddItemsCommand
                    command = AddItemsCommand(self.parent.list_widget, file_paths)
                    self.parent.execute_command(command)
                    
                    # 그 다음 trim 값을 설정
                    for i in range(self.parent.list_widget.count()):
                        item = self.parent.list_widget.item(i)
                        file_path = item.data(Qt.UserRole)
                        if file_path in trim_values:
                            trim_start, trim_end = trim_values[file_path]
                            item_widget = self.parent.list_widget.itemWidget(item)
                            if item_widget:
                                item_widget.set_trim_values(trim_start, trim_end)
                else:
                    QMessageBox.warning(self.parent, "경고", "처리할 수 있는 파일이 없습니다.")
                
        except Exception as e:
            logger.error(f"OTIO 파일 불러오기 실패: {str(e)}", exc_info=True)
            QMessageBox.warning(self.parent, "오류", f"OTIO 파일을 불러오는 중 오류가 발생했습니다: {str(e)}")
