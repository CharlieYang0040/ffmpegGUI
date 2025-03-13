# droppable_line_edit.py

from PySide6.QtWidgets import QLineEdit
from PySide6.QtCore import Qt
import os
from app.ui.commands.commands import ChangeOutputPathCommand
from app.core.commands import command_manager

class DroppableLineEdit(QLineEdit):
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
        new_path = os.path.join(current_dir, f"{file_name}.mp4")

        command = ChangeOutputPathCommand(self, self.text(), new_path)
        command_manager.execute(command)

        event.acceptProposedAction()

    def focusOutEvent(self, event):
        current_text = self.text()
        if current_text and not (current_text.lower().endswith('.mp4') or current_text.lower().endswith('.mov')):
            new_text = current_text + '.mp4'

            if new_text != self.old_text:
                command = ChangeOutputPathCommand(self, self.old_text, new_text)
                command_manager.execute(command)

        super().focusOutEvent(event)