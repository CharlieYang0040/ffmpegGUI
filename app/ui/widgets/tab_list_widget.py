from PySide6.QtWidgets import QTabWidget, QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, QSize
from app.ui.widgets.drag_drop_list_widget import DragDropListWidget
from app.utils.utils import process_file
import logging

logger = logging.getLogger(__name__)

class TabListWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent  # FFmpegGui 인스턴스 저장
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 탭 위젯
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        
        # 새 탭 버튼을 탭바에 직접 추가
        self.add_tab_button = QPushButton("➕")
        self.add_tab_button.setFixedSize(36, 24)  # 버튼 크기 조정
        self.add_tab_button.clicked.connect(self.add_new_tab)
        self.tab_widget.setCornerWidget(self.add_tab_button, Qt.TopRightCorner)
        
        layout.addWidget(self.tab_widget)
        
        # 첫 번째 탭 추가
        self.add_new_tab()
        
        # self.setMinimumSize(QSize(400, 200))
        
    def create_list_widget(self):
        """DragDropListWidget을 생성하고 설정하는 메서드"""
        list_widget = DragDropListWidget(None)  # 임시로 parent를 None으로 설정
        list_widget.process_file_func = process_file
        list_widget.main_window = self.main_window  # FFmpegGui 인스턴스 직접 설정
        
        # parent 설정을 나중에 수행
        list_widget.setParent(self.main_window)
        
        # 아이템 선택 변경 시그널 연결 - 지연 연결 방식으로 변경
        # 나중에 file_list_area가 초기화된 후에 연결될 수 있도록 함
        list_widget.itemSelectionChanged.connect(self.on_item_selection_changed)
        
        # 리스트 위젯의 최소 크기 설정
        list_widget.setMinimumHeight(200)  # 리스트 위젯의 최소 높이 설정
        
        return list_widget
    
    def on_item_selection_changed(self):
        """아이템 선택 변경 시 호출되는 메서드"""
        # file_list_area가 초기화된 후에 이벤트를 전달
        if hasattr(self.main_window, 'file_list_area'):
            self.main_window.file_list_area.on_item_selection_changed()
        
    def add_new_tab(self):
        # 새 탭 컨테이너 생성
        new_tab = QWidget()
        tab_layout = QVBoxLayout(new_tab)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(0)
        
        # 리스트 위젯 생성 및 추가
        list_widget = self.create_list_widget()
        tab_layout.addWidget(list_widget)
        new_tab.setLayout(tab_layout)
        
        # 탭 추가
        tab_count = self.tab_widget.count()
        self.tab_widget.addTab(new_tab, f"시퀀스 {tab_count + 1}")
        self.tab_widget.setCurrentIndex(tab_count)
        logger.info(f"새 탭 추가됨: 시퀀스 {tab_count + 1}")
        
    def close_tab(self, index):
        if self.tab_widget.count() > 1:  # 최소 1개의 탭은 유지
            self.tab_widget.removeTab(index)
            logger.info(f"탭 닫힘: 인덱스 {index}")
            
    def get_current_list_widget(self) -> DragDropListWidget:
        current_tab = self.tab_widget.currentWidget()
        if current_tab:
            return current_tab.findChild(DragDropListWidget)
        return None 