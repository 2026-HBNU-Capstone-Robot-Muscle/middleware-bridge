"""Export the user's color calibration and exhaust all24x6 direction plans."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/control/leap_hand_control'))
from leap_hand_control.recorded_orientation import (
    FACES, ORIENTATIONS, apply, calibration_report, route_to_up, NOMINAL_SECONDS)


def main():
    plans = []
    for before in sorted(ORIENTATIONS):
        for target in FACES:
            route, after = route_to_up(before, target)
            current = before
            for kind in route:
                current = apply(current, kind)
            assert current == after and after[0] == target
            plans.append(dict(before=before, target=target, route=list(route), after=after,
                              nominal_motion_seconds=sum(NOMINAL_SECONDS[k] for k in route)))
    folder = ROOT/'results/recorded_orientation'
    folder.mkdir(exist_ok=True)
    result = dict(calibration=calibration_report(), checked_orientation_target_pairs=len(plans),
                  max_route_legs=max(len(p['route']) for p in plans),
                  plans=plans, devices_opened=False, actual_ROS_routing_tested=False)
    (folder/'calibration_20261124.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('plans','calibration')}))
    for p in plans:
        if p['before'] == FACES:
            print(json.dumps(p))


if __name__ == '__main__':
    main()
