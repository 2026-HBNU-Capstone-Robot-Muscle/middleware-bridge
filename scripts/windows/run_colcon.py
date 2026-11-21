"""Run colcon in-process to avoid distlib launchers breaking Unicode paths."""

import sys

from colcon_core.command import main


if __name__ == "__main__":
    raise SystemExit(main(argv=sys.argv[1:]))
