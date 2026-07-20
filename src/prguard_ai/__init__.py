"""Top-level package for PRGuard AI."""

import os
import sys
import threading

# Suppress noisy onnxruntime/chromadb CPU vendor warning on ARM/emulated platforms.
# The warning is a C-level printf to STDERR_FILENO (fd 2) that fires at any time
# during ONNX model loading (not just at import). We install a permanent stderr
# filter thread that reads from a pipe and drops lines matching the known noise.
os.environ.setdefault("ORT_LOG_LEVEL", "3")
try:
    import onnxruntime  # noqa: F401
    onnxruntime.set_default_logger_severity(3)
except Exception:
    pass

_real_stderr_fd = os.dup(2)
_read_fd, _write_fd = os.pipe()
os.dup2(_write_fd, 2)
os.close(_write_fd)


def _stderr_filter() -> None:
    SUPPRESS_PATTERNS = [b"onnxruntime cpuid_info warning"]
    with os.fdopen(_read_fd, "rb", buffering=0) as reader:
        buf = b""
        while True:
            try:
                chunk = reader.read(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not any(p in line for p in SUPPRESS_PATTERNS):
                    os.write(_real_stderr_fd, line + b"\n")
    os.close(_real_stderr_fd)


_thread = threading.Thread(target=_stderr_filter, daemon=True)
_thread.start()

__all__ = [
    "agents",
    "analysis",
    "cache",
    "config",
    "confidence",
    "cost",
    "dashboard",
    "db",
    "evaluation",
    "github",
    "llm",
    "observability",
    "reliability",
    "security",
    "task_queue",
    "schemas",
]

