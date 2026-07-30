"""Output path helpers shared by drag/drop UI and tests."""

import os
import re

from app.utils.utils import format_drag_to_output, normalize_path_separator


def build_auto_output_path(
    first_input_path: str,
    current_output_path: str = "",
    auto_output_path: bool = True,
    auto_naming: bool = True,
    auto_foldernaming: bool = False,
    extension: str = ".mp4",
) -> str:
    """Return the output path implied by the current auto path/naming toggles."""
    if not first_input_path:
        return normalize_path_separator(current_output_path or f"output{extension}")

    if not extension.startswith("."):
        extension = f".{extension}"

    if auto_output_path:
        output_dir = os.path.dirname(first_input_path)
    else:
        output_dir = os.path.dirname(current_output_path or "") or os.path.expanduser("~")

    if auto_foldernaming:
        output_name = os.path.basename(os.path.dirname(first_input_path)) or "output"
    elif auto_naming:
        output_name = format_drag_to_output(first_input_path) or "output"
    else:
        output_name = os.path.splitext(os.path.basename(current_output_path or ""))[0] or "output"

    return normalize_path_separator(os.path.join(output_dir, f"{output_name}{extension}"))


def next_available_output_path(path: str) -> str:
    """Return a non-existing sibling path with a three-digit suffix."""
    directory, filename = os.path.split(os.path.abspath(path))
    stem, extension = os.path.splitext(filename)
    match = re.match(r"^(.*)_(\d{3,})$", stem)
    if match:
        base_stem = match.group(1)
        number = int(match.group(2)) + 1
    else:
        base_stem = stem
        number = 1

    while True:
        candidate = os.path.join(
            directory,
            f"{base_stem}_{number:03d}{extension}",
        )
        if not os.path.exists(candidate):
            return candidate
        number += 1
