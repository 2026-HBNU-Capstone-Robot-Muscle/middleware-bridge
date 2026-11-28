"""Create a temporary placement profile; never grant calibration verification."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/perception/cube_detection'))
from cube_detection.placement_profile import temporary_profile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration',required=True)
    parser.add_argument('--setup-id',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--from-profile',help='Old placement profile; kept unchanged')
    parser.add_argument('--camera-settings-changed',action='store_true')
    parser.add_argument('--wrist-remounted',action='store_true')
    args=parser.parse_args()
    output=Path(args.output)
    if output.exists():raise ValueError('Preserve existing profile; choose a new output path')
    profile=temporary_profile(args.calibration,args.setup_id,previous=args.from_profile,
        camera_settings_changed=args.camera_settings_changed,wrist_remounted=args.wrist_remounted)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(profile,stream,indent=2,ensure_ascii=False);stream.write('\n')
    print(json.dumps(dict(profile=str(output),setup_id=args.setup_id,temporary=True,
        policy_pose_enabled=False,devices_opened=False),ensure_ascii=False))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError) as exc:print('NOT CREATED:',exc);raise SystemExit(2)
