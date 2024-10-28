# commands.py

from typing import List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from list_widget_item import ListWidgetItem
from utils import debug_print

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
        self.list_widget.add_items(self.items)
        self.added_items = [self.list_widget.item(i) for i in range(self.list_widget.count() - len(self.items), self.list_widget.count())]

    def undo(self):
        for _ in range(len(self.items)):
            self.list_widget.takeItem(self.list_widget.count() - 1)
        self.list_widget.placeholder_visible = self.list_widget.count() == 0

class RemoveItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, items: List[QListWidgetItem]):
        debug_print("[RemoveItemsCommand] 초기화")
        self.list_widget = list_widget
        self.items = items
        # 아이템의 위치와 파일 경로 저장
        self.item_data = [(self.list_widget.row(item), item.data(Qt.UserRole)) for item in items]
        debug_print(f"[RemoveItemsCommand] 제거할 아이템: {self.item_data}")

    def execute(self):
        debug_print("[RemoveItemsCommand] execute 실행")
        for item in self.items:
            self.list_widget.takeItem(self.list_widget.row(item))
        debug_print("[RemoveItemsCommand] 아이템 제거 완료")

    def undo(self):
        debug_print("[RemoveItemsCommand] undo 실행")
        for row, file_path in self.item_data:
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.list_widget.insertItem(row, list_item)
            self.list_widget.setItemWidget(list_item, item_widget)
        debug_print("[RemoveItemsCommand] 아이템 복원 완료")

class ClearListCommand(Command):
    def __init__(self, list_widget: QListWidget):
        debug_print("[ClearListCommand] 초기화")
        self.list_widget = list_widget
        # 현재 모든 아이템의 파일 경로 저장
        self.file_paths = [self.list_widget.item(i).data(Qt.UserRole) 
                          for i in range(self.list_widget.count())]
        debug_print(f"[ClearListCommand] 저장된 아이템: {self.file_paths}")

    def execute(self):
        debug_print("[ClearListCommand] execute 실행")
        self.list_widget.clear()
        self.list_widget.placeholder_visible = True
        debug_print("[ClearListCommand] 목록 비우기 완료")

    def undo(self):
        debug_print("[ClearListCommand] undo 실행")
        for file_path in self.file_paths:
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem()
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)
        self.list_widget.placeholder_visible = False
        debug_print("[ClearListCommand] 목록 복원 완료")

class ReorderItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, old_order: List[str], new_order: List[str]):
        debug_print("[ReorderItemsCommand] 초기화")
        self.list_widget = list_widget
        self.old_order = old_order.copy()  # 복사본 생성
        self.new_order = new_order.copy()  # 복사본 생성
        debug_print(f"[ReorderItemsCommand] 이전 순서: {self.old_order}")
        debug_print(f"[ReorderItemsCommand] 새로운 순서: {self.new_order}")

    def execute(self):
        debug_print("[ReorderItemsCommand] execute 실행")
        self._apply_order(self.new_order)

    def undo(self):
        debug_print("[ReorderItemsCommand] undo 실행")
        self._apply_order(self.old_order)

    def _apply_order(self, order: List[str]):
        debug_print(f"[ReorderItemsCommand] 순서 적용: {order}")
        # 리스트 위젯 초기화
        self.list_widget.clear()
        
        # 새로운 순서로 아이템 추가
        for file_path in order:
            # 항상 새로운 위젯 생성
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem(self.list_widget)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.list_widget.addItem(list_item)
            self.list_widget.setItemWidget(list_item, item_widget)
        
        debug_print("[ReorderItemsCommand] 순서 적용 완료")

class ChangeOutputPathCommand(Command):
    def __init__(self, output_edit, old_path: str, new_path: str):
        debug_print("[ChangeOutputPathCommand] 초기화")
        self.output_edit = output_edit
        self.old_path = old_path
        self.new_path = new_path
        debug_print(f"[ChangeOutputPathCommand] 이전 경로: {old_path}")
        debug_print(f"[ChangeOutputPathCommand] 새 경로: {new_path}")

    def execute(self):
        debug_print("[ChangeOutputPathCommand] execute 실행")
        self.output_edit.setText(self.new_path)
        debug_print("[ChangeOutputPathCommand] 새 경로 설정 완료")

    def undo(self):
        debug_print("[ChangeOutputPathCommand] undo 실행")
        self.output_edit.setText(self.old_path)
        debug_print("[ChangeOutputPathCommand] 이전 경로 복원 완료")