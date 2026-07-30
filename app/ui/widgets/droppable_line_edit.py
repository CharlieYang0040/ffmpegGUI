# droppable_line_edit.py

from PySide6.QtWidgets import QLineEdit
from PySide6.QtCore import Qt
import os
from app.ui.commands.commands import ChangeOutputPathCommand
from app.core.commands import command_manager

class DroppableLineEdit(QLineEdit):
    SUPPORTED_OUTPUT_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm', '.avi'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.old_text = ""  # 이전 텍스트 저장용

    def focusInEvent(self, event):
        self.old_text = self.text()
        super().focusInEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        file_name = event.mimeData().text()
        current_dir = os.path.dirname(self.text()) if self.text() else ""
        if not current_dir:
            current_dir = os.path.expanduser("~")
        extension = getattr(self.parent(), "current_output_extension", ".mp4") or ".mp4"
        if not extension.startswith("."):
            extension = f".{extension}"
        dropped_name = os.path.basename(file_name)
        if os.path.splitext(dropped_name)[1].lower() not in self.SUPPORTED_OUTPUT_EXTENSIONS:
            dropped_name = f"{dropped_name}{extension}"
        new_path = os.path.join(current_dir, dropped_name)

        command = ChangeOutputPathCommand(self, self.text(), new_path)
        command_manager.execute(command)

        event.acceptProposedAction()

    def focusOutEvent(self, event):
        current_text = self.text()
        current_extension = os.path.splitext(current_text)[1].lower()
        if current_text and current_extension not in self.SUPPORTED_OUTPUT_EXTENSIONS:
            extension = getattr(self.parent(), "current_output_extension", ".mp4") or ".mp4"
            if not extension.startswith("."):
                extension = f".{extension}"
            new_text = current_text + extension

            if new_text != self.old_text:
                command = ChangeOutputPathCommand(self, self.old_text, new_text)
                command_manager.execute(command)

        super().focusOutEvent(event)
