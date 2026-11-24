"""Check the pinned right-hand package; never import serial or open devices."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/control/leap_hand_control'))
from leap_hand_control.recorded_assets import RecordedAssets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True)
    args = parser.parse_args()
    try:
        assets = RecordedAssets(args.source_root)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps(dict(status='not_ready', error=str(exc), devices_opened=False)))
        return 2
    print(json.dumps(dict(status='source_check_passed', **assets.summary()), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
