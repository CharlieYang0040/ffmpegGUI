"""Small helpers for running FFmpeg subprocesses safely on Windows."""

from __future__ import annotations

import subprocess
from typing import Iterable, Mapping, Sequence


def decode_process_output(output) -> str:
    """Decode subprocess output without trusting the Windows locale."""
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output)


def iter_decoded_lines(stream) -> Iterable[str]:
    """Yield decoded lines from a binary or text stream."""
    if stream is None:
        return
    while True:
        line = stream.readline()
        if not line:
            break
        yield decode_process_output(line).rstrip("\r\n")


def terminate_process(process, timeout: float = 2.0) -> None:
    """Terminate a process and wait so temp files are released before cleanup."""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=timeout)
    except (OSError, subprocess.SubprocessError, AttributeError):
        try:
            process.kill()
            process.wait(timeout=timeout)
        except (OSError, subprocess.SubprocessError, AttributeError):
            pass


def communicate_process(process, cancel_token=None) -> tuple[int, str, str]:
    """Communicate with a process and return decoded stdout/stderr."""
    if cancel_token:
        cancel_token.register_process(process)
    try:
        stdout, stderr = process.communicate()
        if cancel_token:
            cancel_token.throw_if_cancelled()
        return process.returncode, decode_process_output(stdout), decode_process_output(stderr)
    finally:
        if cancel_token:
            cancel_token.unregister_process(process)


def close_process_pipes(process) -> None:
    for pipe_name in ("stdout", "stderr", "stdin"):
        pipe = getattr(process, pipe_name, None)
        if pipe:
            try:
                pipe.close()
            except OSError:
                pass


def ffmpeg_option_name(key: str) -> str:
    return key if str(key).startswith("-") else f"-{key}"


def build_ffmpeg_option_args(
    options: Mapping[str, object] | None,
    *,
    defaults: Mapping[str, object] | None = None,
    skip_keys: Sequence[str] = (),
) -> list[str]:
    """Build CLI option args while letting explicit preset options override defaults."""
    merged: dict[str, object] = dict(defaults or {})
    merged.update(dict(options or {}))
    skip = set(skip_keys)
    args: list[str] = []
    for key, value in merged.items():
        if key in skip or value is None or value is False:
            continue
        args.append(ffmpeg_option_name(str(key)))
        if value is not True:
            args.append(str(value))
    return args