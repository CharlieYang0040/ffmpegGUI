# commands.py

import logging
from typing import List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from app.ui.widgets.list_widget_item import ListWidgetItem
from app.utils.utils import normalize_path_separator
from app.core.commands import Command
from app.core.models import ClipRange
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
        self.item_data = [
            (
                self.list_widget.row(item),
                item,
                self.list_widget.itemWidget(item),
                _capture_list_item_state(self.list_widget, item),
            )
            for item in items
        ]
        self.logger.info(f"[RemoveItemsCommand] preparing to remove {len(items)} item(s)")

    def execute(self) -> bool:
        try:
            self.logger.info("[RemoveItemsCommand] remove started")
            previous_blocked = self.list_widget.blockSignals(True)
            try:
                for _, item, _, _ in sorted(
                    self.item_data,
                    key=lambda value: value[0],
                    reverse=True,
                ):
                    row = self.list_widget.row(item)
                    if row >= 0 and hasattr(self.list_widget, "detach_item_at"):
                        self.list_widget.detach_item_at(row)
                    elif row >= 0:
                        self.list_widget.takeItem(row)
                if self.list_widget.count():
                    row = min(
                        min(value[0] for value in self.item_data),
                        self.list_widget.count() - 1,
                    )
                    item = self.list_widget.item(row)
                    self.list_widget.setCurrentItem(item)
                    item.setSelected(True)
            finally:
                self.list_widget.blockSignals(previous_blocked)
            if hasattr(self.list_widget, "_finish_structural_edit"):
                self.list_widget._finish_structural_edit(sync_selection=True)
            self.logger.info(f"[RemoveItemsCommand] removed {len(self.items)} item(s)")
            return True
        except Exception as e:
            self.logger.error(f"[RemoveItemsCommand] remove failed: {str(e)}")
            return False

    def undo(self) -> bool:
        try:
            self.logger.info("[RemoveItemsCommand] undo started")
            previous_blocked = self.list_widget.blockSignals(True)
            try:
                for row, item, widget, state in sorted(
                    self.item_data,
                    key=lambda value: value[0],
                ):
                    if hasattr(self.list_widget, "attach_item_at"):
                        self.list_widget.attach_item_at(row, item, widget)
                    else:
                        _restore_list_item_state(self.list_widget, row, state)
                if self.item_data:
                    self.list_widget.setCurrentItem(self.item_data[0][1])
                    self.item_data[0][1].setSelected(True)
            finally:
                self.list_widget.blockSignals(previous_blocked)
            if hasattr(self.list_widget, "_finish_structural_edit"):
                self.list_widget._finish_structural_edit(sync_selection=True)
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
        self.item_bundles = [
            (
                index,
                self.list_widget.item(index),
                self.list_widget.itemWidget(self.list_widget.item(index)),
            )
            for index in range(self.list_widget.count())
        ]
        self.logger.info(f"[ClearListCommand] preparing to clear {len(self.file_paths)} item(s)")

    def execute(self) -> bool:
        try:
            self.logger.info("[ClearListCommand] clear started")
            if hasattr(self.list_widget, "detach_item_at"):
                previous_blocked = self.list_widget.blockSignals(True)
                try:
                    for row in range(self.list_widget.count() - 1, -1, -1):
                        self.list_widget.detach_item_at(row)
                finally:
                    self.list_widget.blockSignals(previous_blocked)
                self.list_widget._finish_structural_edit()
            else:
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
            if hasattr(self.list_widget, "attach_item_at"):
                previous_blocked = self.list_widget.blockSignals(True)
                try:
                    for row, item, widget in self.item_bundles:
                        self.list_widget.attach_item_at(row, item, widget)
                    if self.item_bundles:
                        self.list_widget.setCurrentItem(self.item_bundles[0][1])
                        self.item_bundles[0][1].setSelected(True)
                finally:
                    self.list_widget.blockSignals(previous_blocked)
                self.list_widget._finish_structural_edit(sync_selection=True)
            elif hasattr(self.list_widget, "update_items"):
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
        if hasattr(self.list_widget, "reorder_existing_items"):
            if not self.list_widget.reorder_existing_items(order):
                raise ValueError("기존 클립 ID만으로 목록 순서를 변경할 수 없습니다.")
        elif hasattr(self.list_widget, "update_items"):
            self.list_widget.update_items(order)
        else:
            self.list_widget.clear()
            for state in order:
                _restore_list_item_state(self.list_widget, self.list_widget.count(), state)
        self.logger.info("[ReorderItemsCommand] order applied")


class UpdateClipRangeCommand(Command):
    """Update one existing clip without rebuilding its media widget."""

    def __init__(
        self,
        list_widget: QListWidget,
        clip_id: str,
        old_range: ClipRange,
        new_range: ClipRange,
        description: str = "클립 구간 조정",
    ):
        super().__init__(description)
        self.list_widget = list_widget
        self.clip_id = str(clip_id)
        self.old_range = old_range
        self.new_range = new_range

    def execute(self) -> bool:
        return self._apply(self.new_range)

    def undo(self) -> bool:
        return self._apply(self.old_range)

    def _apply(self, source_range: ClipRange) -> bool:
        try:
            for row in range(self.list_widget.count()):
                item = self.list_widget.item(row)
                widget = self.list_widget.itemWidget(item)
                if widget and getattr(widget, "clip_id", None) == self.clip_id:
                    widget.set_clip_range(source_range, refresh=False)
                    self.list_widget.setCurrentItem(item)
                    item.setSelected(True)
                    if hasattr(self.list_widget, "_refresh_parent_inspector"):
                        self.list_widget._refresh_parent_inspector()
                    return True
            self.logger.error("클립을 찾을 수 없습니다: %s", self.clip_id)
            return False
        except Exception as exc:
            self.logger.error("%s 실패: %s", self.description, exc)
            return False


class DuplicateClipCommand(Command):
    """Duplicate one edit clip while reusing its loaded media data."""

    def __init__(self, list_widget, row: int, new_clip_id: str):
        super().__init__("클립 복제")
        self.list_widget = list_widget
        self.source_row = int(row)
        self.new_clip_id = str(new_clip_id)
        self.duplicate_bundle = None

    def execute(self) -> bool:
        try:
            source_item = self.list_widget.item(self.source_row)
            source_widget = self.list_widget.itemWidget(source_item)
            if source_widget is None or source_widget.get_clip_range() is None:
                return False
            previous_blocked = self.list_widget.blockSignals(True)
            try:
                if self.duplicate_bundle is None:
                    self.duplicate_bundle = self.list_widget.insert_cloned_item(
                        self.source_row + 1,
                        source_widget,
                        self.new_clip_id,
                        source_widget.get_clip_range(),
                        refresh=False,
                    )
                else:
                    self.list_widget.attach_item_at(
                        self.source_row + 1,
                        *self.duplicate_bundle,
                    )
                self.list_widget.clearSelection()
                self.list_widget.setCurrentItem(self.duplicate_bundle[0])
                self.duplicate_bundle[0].setSelected(True)
            finally:
                self.list_widget.blockSignals(previous_blocked)
            self.list_widget._finish_structural_edit()
            return True
        except Exception as exc:
            self.logger.error("%s 실패: %s", self.description, exc)
            return False

    def undo(self) -> bool:
        try:
            row = self.list_widget.row(self.duplicate_bundle[0])
            if row < 0:
                return False
            previous_blocked = self.list_widget.blockSignals(True)
            try:
                self.duplicate_bundle = self.list_widget.detach_item_at(row)
                source_item = self.list_widget.item(
                    min(self.source_row, self.list_widget.count() - 1)
                )
                if source_item is not None:
                    self.list_widget.setCurrentItem(source_item)
                    source_item.setSelected(True)
            finally:
                self.list_widget.blockSignals(previous_blocked)
            self.list_widget._finish_structural_edit()
            return True
        except Exception as exc:
            self.logger.error("%s 실행 취소 실패: %s", self.description, exc)
            return False


class SplitClipCommand(Command):
    """Split one edit clip without reloading either source."""

    def __init__(
        self,
        list_widget,
        row: int,
        split_boundary: int,
        left_clip_id: str,
        right_clip_id: str,
    ):
        super().__init__("클립 분할")
        self.list_widget = list_widget
        self.row = int(row)
        self.split_boundary = int(split_boundary)
        self.left_clip_id = str(left_clip_id)
        self.right_clip_id = str(right_clip_id)
        item = self.list_widget.item(self.row)
        self.original_item = item
        self.original_widget = self.list_widget.itemWidget(item)
        self.original_clip_id = str(self.original_widget.clip_id)
        self.original_range = self.original_widget.get_clip_range()
        self.left_range, self.right_range = self.original_range.split(
            self.split_boundary
        )
        self.right_bundle = None

    def execute(self) -> bool:
        try:
            previous_blocked = self.list_widget.blockSignals(True)
            try:
                self.original_widget.clip_id = self.left_clip_id
                self.original_widget.set_clip_range(self.left_range, refresh=False)
                if self.right_bundle is None:
                    self.right_bundle = self.list_widget.insert_cloned_item(
                        self.row + 1,
                        self.original_widget,
                        self.right_clip_id,
                        self.right_range,
                        refresh=False,
                    )
                else:
                    self.list_widget.attach_item_at(
                        self.row + 1,
                        *self.right_bundle,
                    )
                self.list_widget.clearSelection()
                self.list_widget.setCurrentItem(self.right_bundle[0])
                self.right_bundle[0].setSelected(True)
            finally:
                self.list_widget.blockSignals(previous_blocked)
            self.list_widget._finish_structural_edit()
            return True
        except Exception as exc:
            self.logger.error("%s 실패: %s", self.description, exc)
            return False

    def undo(self) -> bool:
        try:
            right_row = self.list_widget.row(self.right_bundle[0])
            if right_row < 0:
                return False
            previous_blocked = self.list_widget.blockSignals(True)
            try:
                self.right_bundle = self.list_widget.detach_item_at(right_row)
                self.original_widget.clip_id = self.original_clip_id
                self.original_widget.set_clip_range(
                    self.original_range,
                    refresh=False,
                )
                self.list_widget.clearSelection()
                self.list_widget.setCurrentItem(self.original_item)
                self.original_item.setSelected(True)
            finally:
                self.list_widget.blockSignals(previous_blocked)
            self.list_widget._finish_structural_edit()
            return True
        except Exception as exc:
            self.logger.error("%s 실행 취소 실패: %s", self.description, exc)
            return False


class ResetClipRangesCommand(Command):
    """Reset every clip range without reconstructing list items."""

    def __init__(self, list_widget):
        super().__init__("모든 컷 구간 초기화")
        self.list_widget = list_widget
        self.old_ranges = {}
        for row in range(self.list_widget.count()):
            widget = self.list_widget.itemWidget(self.list_widget.item(row))
            self.old_ranges[str(widget.clip_id)] = widget.get_clip_range()

    def execute(self) -> bool:
        return self._apply(reset=True)

    def undo(self) -> bool:
        return self._apply(reset=False)

    def _apply(self, reset: bool) -> bool:
        try:
            for row in range(self.list_widget.count()):
                widget = self.list_widget.itemWidget(self.list_widget.item(row))
                source_range = (
                    ClipRange(0, widget.total_frames)
                    if reset
                    else self.old_ranges[str(widget.clip_id)]
                )
                widget.set_clip_range(source_range, refresh=False)
            self.list_widget._finish_structural_edit()
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
