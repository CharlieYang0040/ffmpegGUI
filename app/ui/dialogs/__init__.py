from importlib import import_module

_EXPORTS = {
    "EncodingProgressDialog": ("app.ui.dialogs.progress_dialog", "EncodingProgressDialog"),
    "ProgressSignals": ("app.ui.dialogs.progress_dialog", "ProgressSignals"),
    "EncodingOptionsDialog": ("app.ui.dialogs.encoding_options_dialog", "EncodingOptionsDialog"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
