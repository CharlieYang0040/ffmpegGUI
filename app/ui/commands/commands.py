# commands.py

import logging
from typing import List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from app.ui.widgets.list_widget_item import ListWidgetItem
from app.utils.utils import normalize_path_separator

# 로깅 설정
logger = logging.getLogger(__name__)

class Command:
    def execute(self):
        pass
    
    def undo(self):
        pass

class AddItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, items: List[str]):
        self.list_widget = list_widget
        self.items = items
        self.added_items = []

    def execute(self):
        logger.info("[AddItemsCommand] 아이템 추가 시작")
        self.list_widget.add_items(self.items)
        self.added_items = [self.list_widget.item(i) for i in range(self.list_widget.count() - len(self.items), self.list_widget.count())]
        logger.info("[AddItemsCommand] 아이템 추가 완료")
    def undo(self):
        logger.info("[AddItemsCommand] undo 실행")
        for _ in range(len(self.items)):
            self.list_widget.takeItem(self.list_widget.count() - 1)
        self.list_widget.placeholder_visible = self.list_widget.count() == 0
        logger.info("[AddItemsCommand] undo 완료")

class RemoveItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, items: List[QListWidgetItem]):
        logger.debug("[RemoveItemsCommand] 초기화")
        self.list_widget = list_widget
        self.items = items
        self.item_data = [(self.list_widget.row(item), item.data(Qt.UserRole)) for item in items]
        logger.info(f"[RemoveItemsCommand] {len(items)}개 아이템 제거 예정")

    def execute(self):
        logger.info("[RemoveItemsCommand] 아이템 제거 시작")
        for item in self.items:
            self.list_widget.takeItem(self.list_widget.row(item))
        logger.info(f"[RemoveItemsCommand] {len(self.items)}개 아이템 제거 완료")

    def undo(self):
        logger.info("[RemoveItemsCommand] undo 실행")
        for row, file_path in self.item_data:
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.list_widget.insertItem(row, list_item)
            self.list_widget.setItemWidget(list_item, item_widget)
        logger.info("[RemoveItemsCommand] 아이템 복원 완료")

class ClearListCommand(Command):
    def __init__(self, list_widget: QListWidget):
        logger.debug("[ClearListCommand] 초기화")
        self.list_widget = list_widget
        self.file_paths = [self.list_widget.item(i).data(Qt.UserRole) 
                          for i in range(self.list_widget.count())]
        logger.info(f"[ClearListCommand] {len(self.file_paths)}개 아이템 초기화 예정")

    def execute(self):
        logger.info("[ClearListCommand] 목록 초기화 시작")
        self.list_widget.clear()
        self.list_widget.placeholder_visible = True
        logger.info("[ClearListCommand] 목록 초기화 완료")

    def undo(self):
        logger.info("[ClearListCommand] undo 실행")
        for file_path in self.file_paths:
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)
        self.list_widget.placeholder_visible = False
        logger.info("[ClearListCommand] 목록 복원 완료")

class ReorderItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, old_order: List[str], new_order: List[str]):
        logger.debug("[ReorderItemsCommand] 초기화")
        self.list_widget = list_widget
        self.old_order = old_order.copy()
        self.new_order = new_order.copy()
        logger.info(f"[ReorderItemsCommand] {len(new_order)}개 아이템 재정렬 예정")

    def execute(self):
        logger.info("[ReorderItemsCommand] 아이템 재정렬 시작")
        self._apply_order(self.new_order)

    def undo(self):
        logger.info("[ReorderItemsCommand] undo 실행")
        self._apply_order(self.old_order)

    def _apply_order(self, order: List[str]):
        logger.info(f"[ReorderItemsCommand] 아이템 재정렬 시작")
        self.list_widget.clear()
        
        for file_path in order:
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem(self.list_widget)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)
        
        logger.info("[ReorderItemsCommand] 아이템 재정렬 완료")

class ChangeOutputPathCommand(Command):
    def __init__(self, output_edit, old_path: str, new_path: str):
        logger.debug("[ChangeOutputPathCommand] 초기화")
        self.output_edit = output_edit
        self.old_path = normalize_path_separator(old_path)
        self.new_path = normalize_path_separator(new_path)
        logger.info(f"[ChangeOutputPathCommand] 출력 경로 변경: {old_path} -> {new_path}")

    def execute(self):
        logger.info("[ChangeOutputPathCommand] 출력 경로 변경 시작")
        self.output_edit.setText(self.new_path)
        logger.info("[ChangeOutputPathCommand] 새 경로 설정 완료")

    def undo(self):
        logger.info("[ChangeOutputPathCommand] undo 실행")
        self.output_edit.setText(self.old_path)
        logger.info("[ChangeOutputPathCommand] 이전 경로 복원 완료")