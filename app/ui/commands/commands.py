# commands.py

import logging
from typing import List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from app.ui.widgets.list_widget_item import ListWidgetItem
from app.utils.utils import normalize_path_separator
from app.core.commands import Command
from app.services.logging_service import LoggingService

# 로깅 설정
logger = LoggingService().get_logger(__name__)

class AddItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, items: List[str]):
        super().__init__(f"{len(items)}개 아이템 추가")
        self.list_widget = list_widget
        self.items = items
        self.added_items = []

    def execute(self) -> bool:
        try:
            self.logger.info("[AddItemsCommand] 아이템 추가 시작")
            self.list_widget.add_items(self.items)
            self.added_items = [self.list_widget.item(i) for i in range(self.list_widget.count() - len(self.items), self.list_widget.count())]
            self.logger.info("[AddItemsCommand] 아이템 추가 완료")
            return True
        except Exception as e:
            self.logger.error(f"[AddItemsCommand] 아이템 추가 중 오류: {str(e)}")
            return False

    def undo(self) -> bool:
        try:
            self.logger.info("[AddItemsCommand] undo 실행")
            for _ in range(len(self.items)):
                self.list_widget.takeItem(self.list_widget.count() - 1)
            self.list_widget.placeholder_visible = self.list_widget.count() == 0
            self.logger.info("[AddItemsCommand] undo 완료")
            return True
        except Exception as e:
            self.logger.error(f"[AddItemsCommand] undo 중 오류: {str(e)}")
            return False

def _capture_list_item_state(list_widget: QListWidget, item: QListWidgetItem) -> dict:
    if hasattr(list_widget, "_state_from_item"):
        return list_widget._state_from_item(item)
    return {"file_path": item.data(Qt.UserRole), "trim_start": 0, "trim_end": 0}


def _normalize_item_state(list_widget: QListWidget, state) -> dict:
    if hasattr(list_widget, "_coerce_item_state"):
        return list_widget._coerce_item_state(state)
    if isinstance(state, dict):
        return {
            "file_path": state.get("file_path", ""),
            "trim_start": int(state.get("trim_start", 0) or 0),
            "trim_end": int(state.get("trim_end", 0) or 0),
        }
    return {"file_path": state, "trim_start": 0, "trim_end": 0}


def _restore_list_item_state(list_widget: QListWidget, row: int, state) -> None:
    state = _normalize_item_state(list_widget, state)
    if hasattr(list_widget, "insert_item_state"):
        list_widget.insert_item_state(row, state)
        return

    item_widget = ListWidgetItem(state["file_path"])
    if hasattr(item_widget, "set_trim_values"):
        try:
            item_widget.set_trim_values(state["trim_start"], state["trim_end"], refresh=False)
        except TypeError:
            item_widget.set_trim_values(state["trim_start"], state["trim_end"])
    list_item = QListWidgetItem()
    list_item.setSizeHint(item_widget.sizeHint())
    list_item.setData(Qt.UserRole, state["file_path"])
    list_widget.insertItem(row, list_item)
    list_widget.setItemWidget(list_item, item_widget)


class RemoveItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, items: List[QListWidgetItem]):
        super().__init__(f"Remove {len(items)} item(s)")
        self.list_widget = list_widget
        self.items = items
        self.item_data = [(self.list_widget.row(item), _capture_list_item_state(self.list_widget, item)) for item in items]
        self.logger.info(f"[RemoveItemsCommand] preparing to remove {len(items)} item(s)")

    def execute(self) -> bool:
        try:
            self.logger.info("[RemoveItemsCommand] remove started")
            for item in self.items:
                self.list_widget.takeItem(self.list_widget.row(item))
            self.logger.info(f"[RemoveItemsCommand] removed {len(self.items)} item(s)")
            return True
        except Exception as e:
            self.logger.error(f"[RemoveItemsCommand] remove failed: {str(e)}")
            return False

    def undo(self) -> bool:
        try:
            self.logger.info("[RemoveItemsCommand] undo started")
            for row, state in self.item_data:
                _restore_list_item_state(self.list_widget, row, state)
            self.logger.info("[RemoveItemsCommand] undo restored items")
            return True
        except Exception as e:
            self.logger.error(f"[RemoveItemsCommand] undo failed: {str(e)}")
            return False


class ClearListCommand(Command):
    def __init__(self, list_widget: QListWidget):
        super().__init__("Clear list")
        self.list_widget = list_widget
        if hasattr(self.list_widget, "get_all_item_states"):
            self.item_states = self.list_widget.get_all_item_states()
        else:
            self.item_states = [
                _capture_list_item_state(self.list_widget, self.list_widget.item(i))
                for i in range(self.list_widget.count())
            ]
        self.file_paths = [state["file_path"] for state in self.item_states]
        self.logger.info(f"[ClearListCommand] preparing to clear {len(self.file_paths)} item(s)")

    def execute(self) -> bool:
        try:
            self.logger.info("[ClearListCommand] clear started")
            self.list_widget.clear()
            self.list_widget.placeholder_visible = True
            self.logger.info("[ClearListCommand] clear complete")
            return True
        except Exception as e:
            self.logger.error(f"[ClearListCommand] clear failed: {str(e)}")
            return False

    def undo(self) -> bool:
        try:
            self.logger.info("[ClearListCommand] undo started")
            if hasattr(self.list_widget, "update_items"):
                self.list_widget.update_items(self.item_states)
            else:
                for state in self.item_states:
                    _restore_list_item_state(self.list_widget, self.list_widget.count(), state)
            self.list_widget.placeholder_visible = self.list_widget.count() == 0
            self.logger.info("[ClearListCommand] undo restored list")
            return True
        except Exception as e:
            self.logger.error(f"[ClearListCommand] undo failed: {str(e)}")
            return False


class ReorderItemsCommand(Command):
    def __init__(self, list_widget: QListWidget, old_order: List, new_order: List):
        super().__init__("Reorder items")
        self.list_widget = list_widget
        self.old_order = self._normalize_order(old_order)
        self.new_order = self._normalize_order(new_order)
        self.logger.info(f"[ReorderItemsCommand] preparing to reorder {len(new_order)} item(s)")

    def execute(self) -> bool:
        try:
            self.logger.info("[ReorderItemsCommand] reorder started")
            self._apply_order(self.new_order)
            return True
        except Exception as e:
            self.logger.error(f"[ReorderItemsCommand] reorder failed: {str(e)}")
            return False

    def undo(self) -> bool:
        try:
            self.logger.info("[ReorderItemsCommand] undo started")
            self._apply_order(self.old_order)
            return True
        except Exception as e:
            self.logger.error(f"[ReorderItemsCommand] undo failed: {str(e)}")
            return False

    def _normalize_order(self, order: List) -> List[dict]:
        existing_states = {}
        if hasattr(self.list_widget, "get_all_item_states"):
            for state in self.list_widget.get_all_item_states():
                existing_states.setdefault(state["file_path"], []).append(state)

        normalized = []
        for item in order:
            if isinstance(item, dict):
                normalized.append(_normalize_item_state(self.list_widget, item))
                continue

            candidates = existing_states.get(item, [])
            if candidates:
                normalized.append(candidates.pop(0))
            else:
                normalized.append(_normalize_item_state(self.list_widget, item))
        return normalized

    def _apply_order(self, order: List[dict]):
        self.logger.info("[ReorderItemsCommand] applying order")
        if hasattr(self.list_widget, "update_items"):
            self.list_widget.update_items(order)
        else:
            self.list_widget.clear()
            for state in order:
                _restore_list_item_state(self.list_widget, self.list_widget.count(), state)
        self.logger.info("[ReorderItemsCommand] order applied")


class ReplaceListStateCommand(Command):
    """Replace an edit sequence atomically for split/duplicate operations."""

    def __init__(
        self,
        list_widget: QListWidget,
        old_states: List,
        new_states: List,
        old_selected_row: int,
        new_selected_row: int,
        description: str,
    ):
        super().__init__(description)
        self.list_widget = list_widget
        self.old_states = [_normalize_item_state(list_widget, state) for state in old_states]
        self.new_states = [_normalize_item_state(list_widget, state) for state in new_states]
        self.old_selected_row = old_selected_row
        self.new_selected_row = new_selected_row

    def execute(self) -> bool:
        return self._apply(self.new_states, self.new_selected_row)

    def undo(self) -> bool:
        return self._apply(self.old_states, self.old_selected_row)

    def _apply(self, states: List[dict], selected_row: int) -> bool:
        try:
            self.list_widget.update_items(states)
            if 0 <= selected_row < self.list_widget.count():
                self.list_widget.setCurrentRow(selected_row)
            return True
        except Exception as exc:
            self.logger.error("%s 실패: %s", self.description, exc)
            return False


class ChangeOutputPathCommand(Command):
    def __init__(self, output_edit, old_path: str, new_path: str):
        super().__init__(f"출력 경로 변경: {old_path} → {new_path}")
        self.output_edit = output_edit
        self.old_path = normalize_path_separator(old_path)
        self.new_path = normalize_path_separator(new_path)
        self.logger.info(f"[ChangeOutputPathCommand] 출력 경로 변경: {old_path} -> {new_path}")

    def execute(self) -> bool:
        try:
            self.logger.info("[ChangeOutputPathCommand] 출력 경로 변경 시작")
            self.output_edit.setText(self.new_path)
            self.logger.info("[ChangeOutputPathCommand] 새 경로 설정 완료")
            return True
        except Exception as e:
            self.logger.error(f"[ChangeOutputPathCommand] 출력 경로 변경 중 오류: {str(e)}")
            return False

    def undo(self) -> bool:
        try:
            self.logger.info("[ChangeOutputPathCommand] undo 실행")
            self.output_edit.setText(self.old_path)
            self.logger.info("[ChangeOutputPathCommand] 이전 경로 복원 완료")
            return True
        except Exception as e:
            self.logger.error(f"[ChangeOutputPathCommand] undo 중 오류: {str(e)}")
            return False
