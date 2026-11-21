"""Run ROS 2 CLI commands without Windows console-script launchers."""

import runpy
import sys
from pathlib import Path

from ament_index_python.packages import get_package_prefix
from ros2cli.cli import main as ros2_main


def run_ros2(args: list[str]) -> int | str | None:
    if len(args) >= 3 and args[0] == "run":
        package, executable = args[1], args[2]
        try:
            prefix = Path(get_package_prefix(package))
        except (LookupError, ValueError):
            prefix = None
        if prefix is not None:
            entry_point = prefix / "lib" / package / f"{executable}-script.py"
            if entry_point.is_file():
                sys.argv = [str(entry_point), *args[3:]]
                runpy.run_path(str(entry_point), run_name="__main__")
                return 0

    return ros2_main(argv=args)


if __name__ == "__main__":
    raise SystemExit(run_ros2(sys.argv[1:]))
