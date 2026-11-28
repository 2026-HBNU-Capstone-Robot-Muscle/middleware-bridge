"""Explicit READ-only16-motor probe; default mode opens no device."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/control/leap_hand_control'))
from leap_hand_control.dynamixel_reader import DynamixelReader
from leap_hand_control.hardware_adapter import MOTOR_IDS, sim_positions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--port', default='')
    args = parser.parse_args()
    if not args.read_only:
        print('CHECK ONLY: no motor port opened. Use --read-only --port PORT for READ/PING only.')
        return 0
    if not args.port:
        parser.error('--read-only requires an explicit --port')
    folder = ROOT / 'results/leap_adapter'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    path = folder / f'read_only_{stamp}.json'
    reader = DynamixelReader(args.port)
    report = dict(mode='read_only', port=args.port, baud=1_000_000,
                  motor_ids_in_sim_order=list(MOTOR_IDS), motor_writes=0,
                  torque_changes=0, samples=[], passed=False)
    try:
        reader.open()
        report['inventory'] = reader.inventory
        for _ in range(2):
            sample = reader.read(time.monotonic()).validate()
            report['samples'].append(dict(
                acquired_at_monotonic=sample.acquired_at,
                positions_id_order=list(sample.positions), goals_id_order=list(sample.goals),
                position_rad_sim_order=sim_positions(sample.positions),
                current_ma=list(sample.current_ma), voltage_v=list(sample.voltage_v),
                temperature_c=list(sample.temperature_c), torque=list(sample.torque),
                errors=list(sample.errors)))
            time.sleep(.075)
        report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        reader.close()
        report['port_closed'] = True
        path.write_bytes((json.dumps(report, indent=2)+'\n').encode('utf-8'))
    print(json.dumps({k:v for k,v in report.items() if k not in ('samples','inventory')}))
    print(f'Report: {path}')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
