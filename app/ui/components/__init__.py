from importlib import import_module

_EXPORTS = {
    "PreviewAreaComponent": ("app.ui.components.preview_area", "PreviewAreaComponent"),
    "ControlAreaComponent": ("app.ui.components.control_area", "ControlAreaComponent"),
    "FileListAreaComponent": ("app.ui.components.file_list_area", "FileListAreaComponent"),
    "OtioControlsComponent": ("app.ui.components.otio_controls", "OtioControlsComponent"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
