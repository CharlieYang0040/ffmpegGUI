# drag_drop_list_widget.py

import logging
import os

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QDrag, QDragEnterEvent, QDropEvent, QPainter
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListWidget, QListWidgetItem

from app.core.commands import command_manager
from app.core.output_naming import build_auto_output_path
from app.ui.commands.commands import AddItemsCommand, ChangeOutputPathCommand, ReorderItemsCommand
from app.ui.widgets.list_widget_item import ListWidgetItem
from app.utils.utils import format_drag_to_output, is_media_file, process_file, process_image_sequences

logger = logging.getLogger(__name__)


class DragDropListWidget(QListWidget):
    def __init__(self, parent=None, process_file_func=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.process_file_func = process_file_func or process_file
        self.old_order = []
        self.drag_start_position = None

        self.setViewportMargins(0, 0, 0, 0)
        self.placeholder_text = "미디어 추가"
        self.placeholder_subtext = ""
        self.placeholder_visible = True
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.itemDoubleClicked.connect(self.on_item_double_clicked)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def startDrag(self, supportedActions):
        self.old_order = self.get_all_item_states()
        drag = QDrag(self)
        mime_data = QMimeData()

        current_item = self.currentItem()
        if current_item:
            file_path = current_item.data(Qt.UserRole)
            file_name = os.path.basename(format_drag_to_output(file_path))
            mime_data.setText(file_name)
            mime_data.setData("application/x-qabstractitemmodeldatalist", b"")

        drag.setMimeData(mime_data)
        drag.exec_(Qt.MoveAction)

    def handle_new_files(self, links):
        """Handle files from drag/drop and the add-files dialog."""
        if not links or not getattr(self, "main_window", None):
            return

        command = AddItemsCommand(self, links)
        command_manager.execute(command)
        logger.info("%s개 파일 추가됨", len(links))

        output_path = build_auto_output_path(
            links[0],
            self.main_window.output_edit.text(),
            auto_output_path=(
                hasattr(self.main_window, "auto_output_path_checkbox")
                and self.main_window.auto_output_path_checkbox.isChecked()
            ),
            auto_naming=(
                hasattr(self.main_window, "auto_naming_checkbox")
                and self.main_window.auto_naming_checkbox.isChecked()
            ),
            auto_foldernaming=(
                hasattr(self.main_window, "auto_foldernaming_checkbox")
                and self.main_window.auto_foldernaming_checkbox.isChecked()
            ),
            extension=getattr(self.main_window, "current_output_extension", ".mp4"),
        )
        command = ChangeOutputPathCommand(self.main_window.output_edit, self.main_window.output_edit.text(), output_path)
        command_manager.execute(command)
        self._refresh_parent_inspector()

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            links = []
            for url in event.mimeData().urls():
                if not url.isLocalFile():
                    continue
                file_path = str(url.toLocalFile())
                if os.path.isdir(file_path):
                    links.extend(self.parse_folder(file_path))
                else:
                    processed_path = self.process_file_func(file_path)
                    if processed_path:
                        links.append(processed_path)
            self.handle_new_files(links)
            return

        event.setDropAction(Qt.MoveAction)
        super().dropEvent(event)
        new_order = self.get_all_item_states()
        if self._state_paths(self.old_order) != self._state_paths(new_order):
            command = ReorderItemsCommand(self, self.old_order, new_order)
            command_manager.execute(command)
            self._refresh_parent_inspector()

    def parse_folder(self, folder_path):
        files = []
        for root, _, filenames in os.walk(folder_path):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                if is_media_file(file_path):
                    files.append(file_path)
        return process_image_sequences(files)

    @staticmethod
    def _coerce_item_state(state):
        def as_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        if isinstance(state, dict):
            return {
                "file_path": state.get("file_path", ""),
                "trim_start": as_int(state.get("trim_start", 0)),
                "trim_end": as_int(state.get("trim_end", 0)),
                "clip_id": str(state.get("clip_id", "") or ""),
            }
        return {"file_path": state, "trim_start": 0, "trim_end": 0, "clip_id": ""}

    @staticmethod
    def _state_paths(states):
        return [state.get("file_path", state) if isinstance(state, dict) else state for state in states]

    def _state_from_item(self, item):
        file_path = item.data(Qt.UserRole) if item else ""
        trim_start = 0
        trim_end = 0
        widget = self.itemWidget(item) if item else None
        if widget and hasattr(widget, "get_trim_values"):
            trim_start, trim_end = widget.get_trim_values()
        return {
            "file_path": file_path,
            "trim_start": int(trim_start),
            "trim_end": int(trim_end),
            "clip_id": str(getattr(widget, "clip_id", "") or ""),
        }

    def _make_list_item(self, state):
        state = self._coerce_item_state(state)
        item_widget = ListWidgetItem(state["file_path"])
        if state.get("clip_id"):
            item_widget.clip_id = state["clip_id"]
        if hasattr(item_widget, "set_trim_values"):
            try:
                item_widget.set_trim_values(state["trim_start"], state["trim_end"], refresh=False)
            except TypeError:
                item_widget.set_trim_values(state["trim_start"], state["trim_end"])

        list_item = QListWidgetItem()
        list_item.setSizeHint(item_widget.sizeHint())
        list_item.setData(Qt.UserRole, state["file_path"])
        return list_item, item_widget

    def add_item_state(self, state):
        list_item, item_widget = self._make_list_item(state)
        self.addItem(list_item)
        self.setItemWidget(list_item, item_widget)

    def insert_item_state(self, row, state):
        list_item, item_widget = self._make_list_item(state)
        self.insertItem(row, list_item)
        self.setItemWidget(list_item, item_widget)

    def add_items(self, file_paths):
        for file_path in file_paths:
            self.add_item_state(file_path)
        self.placeholder_visible = self.count() == 0
        self.viewport().update()
        self._refresh_parent_inspector()

    def update_items(self, new_items):
        existing_states = {}
        for state in self.get_all_item_states():
            existing_states.setdefault(state["file_path"], []).append(state)

        resolved_states = []
        for item in new_items:
            state = self._coerce_item_state(item)
            if not isinstance(item, dict):
                candidates = existing_states.get(state["file_path"], [])
                if candidates:
                    state = candidates.pop(0)
            resolved_states.append(state)

        self.clear()
        for state in resolved_states:
            self.add_item_state(state)
        self.placeholder_visible = self.count() == 0
        self.viewport().update()
        self._refresh_parent_inspector()

    def get_all_item_states(self):
        return [self._state_from_item(self.item(index)) for index in range(self.count())]

    def get_all_file_paths(self):
        return [state["file_path"] for state in self.get_all_item_states()]

    def get_selected_file_path(self):
        selected_items = self.selectedItems()
        if selected_items:
            return selected_items[0].data(Qt.UserRole)
        return None

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        for index in deselected.indexes():
            item = self.item(index.row())
            widget = self.itemWidget(item)
            if widget:
                widget.setSelected(False)
        for index in selected.indexes():
            item = self.item(index.row())
            widget = self.itemWidget(item)
            if widget:
                widget.setSelected(True)
        self._refresh_parent_inspector()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.placeholder_visible and self.count() == 0:
            painter = QPainter(self.viewport())
            painter.save()
            col = self.palette().placeholderText().color()
            painter.setPen(QColor("#d7dde5"))

            main_font = QApplication.font()
            main_font.setPointSize(11)
            main_font.setBold(False)
            painter.setFont(main_font)
            fm = painter.fontMetrics()
            main_text_rect = fm.boundingRect(self.viewport().rect(), Qt.AlignCenter, self.placeholder_text)
            painter.drawText(main_text_rect, Qt.AlignCenter, self.placeholder_text)

            sub_font = QApplication.font()
            sub_font.setPointSize(10)
            painter.setFont(sub_font)
            fm = painter.fontMetrics()
            sub_text_rect = fm.boundingRect(self.viewport().rect(), Qt.AlignCenter, self.placeholder_subtext)
            sub_text_rect.moveTop(main_text_rect.bottom() + 1)
            painter.drawText(sub_text_rect, Qt.AlignCenter, self.placeholder_subtext)
            painter.restore()

    def clear(self):
        super().clear()
        self.placeholder_visible = True
        self.viewport().update()
        self._refresh_parent_inspector()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if not item:
                self.clearSelection()
                return
            self.drag_start_position = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if not self.drag_start_position:
            return
        if (event.pos() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        if self.currentItem():
            self.startDrag(Qt.MoveAction)

    def handle_double_click(self, file_path):
        parent = self.parent()
        if hasattr(parent, "open_folder"):
            parent.open_folder(file_path)

    def on_item_double_clicked(self, item):
        file_path = item.data(Qt.UserRole)
        parent = self.parent()
        if file_path and hasattr(parent, "open_folder"):
            parent.open_folder(file_path)

    def remove_item(self, item):
        self.takeItem(self.row(item))
        self.placeholder_visible = self.count() == 0
        self.viewport().update()
        self._refresh_parent_inspector()

    def _refresh_parent_inspector(self):
        main_window = getattr(self, "main_window", None)
        if main_window and hasattr(main_window, "refresh_job_inspector"):
            main_window.refresh_job_inspector()
