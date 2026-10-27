"""Run RoboStack's ROS 2 rosbridge server with Windows signal handling."""

import asyncio
import runpy
import signal
import sys
from pathlib import Path

from ament_index_python.packages import get_package_prefix


def _add_windows_signal_handler(loop, sig, callback, *args):
    """Adapt signal registration to the Windows Proactor event loop."""
    signal.signal(
        sig,
        lambda *_: loop.call_soon_threadsafe(callback, *args),
    )


def _find_rosbridge_entrypoint() -> Path:
    package_prefix = Path(get_package_prefix("rosbridge_server"))
    candidates = (
        package_prefix / "lib" / "rosbridge_server" / "rosbridge_websocket",
        package_prefix / "lib" / "rosbridge_server" / "rosbridge_websocket.py",
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    searched = "\n".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        "Could not find the rosbridge_websocket entry point. Searched:\n"
        f"{searched}"
    )


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("This launcher is for Windows Pixi environments only.")

    # asyncio's Windows Proactor loop raises NotImplementedError for this API.
    # Python's signal.signal runs on the main thread and schedules the callback
    # safely on the active event loop when Ctrl+C or SIGTERM is received.
    asyncio.ProactorEventLoop.add_signal_handler = _add_windows_signal_handler

    runpy.run_path(str(_find_rosbridge_entrypoint()), run_name="__main__")


if __name__ == "__main__":
    main()
