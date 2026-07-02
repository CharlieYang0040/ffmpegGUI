import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from app.ui.components.timeline import TimelineWidget
    from app.ui.main_window import FFmpegGui
    from app.ui.widgets.drag_drop_list_widget import DragDropListWidget
except ModuleNotFoundError:  # pragma: no cover - exercised only without Qt installed
    QApplication = None
    Qt = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class UIRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_update_items_preserves_trim_values_for_existing_paths(self):
        widget = DragDropListWidget()
        widget.add_items(["C:/media/a.mp4", "C:/media/b.mp4"])
        widget.itemWidget(widget.item(0)).set_trim_values(12, 5)

        widget.update_items(["C:/media/b.mp4", "C:/media/a.mp4"])

        restored = None
        for row in range(widget.count()):
            item = widget.item(row)
            if item.data(Qt.UserRole) == "C:/media/a.mp4":
                restored = widget.itemWidget(item)
                break
        self.assertIsNotNone(restored)
        self.assertEqual(restored.get_trim_values(), (12, 5))

    def test_timeline_trim_apply_allows_in_point_after_previous_out(self):
        timeline = TimelineWidget()
        timeline.set_video_info(100, 24.0, 100 / 24.0)
        timeline.set_out_point(50)

        class FakeItemWidget:
            def get_trim_values(self):
                return 80, 0

        class FakeListWidget:
            def currentItem(self):
                return object()

            def itemWidget(self, _item):
                return FakeItemWidget()

        window = SimpleNamespace(
            preview_area=SimpleNamespace(timeline=SimpleNamespace(timeline_widget=timeline)),
            list_widget=FakeListWidget(),
            _syncing_timeline_trim=False,
        )

        FFmpegGui.apply_selected_item_trim_to_timeline(window)

        self.assertEqual((timeline.in_point, timeline.out_point), (81, 100))
        self.assertFalse(window._syncing_timeline_trim)

    def test_preset_extension_updates_known_output_container(self):
        class FakeLineEdit:
            def __init__(self, value):
                self.value = value

            def text(self):
                return self.value

            def setText(self, value):
                self.value = value

        window = SimpleNamespace(
            output_edit=FakeLineEdit("C:/renders/review.mp4"),
            auto_naming_checkbox=SimpleNamespace(isChecked=lambda: False),
        )

        FFmpegGui.update_output_extension_for_preset(window, ".webm")

        self.assertEqual(window.output_edit.text(), "C:/renders/review.webm")


if __name__ == "__main__":
    unittest.main()
