"""Read-only, pinned source contract for the existing right-hand controller."""
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from leap_hand_control.recorded_orientation import FACE_UP_PRIMITIVE

MANIFEST_PATH = 'right_hand_rotation_20261125/middleware_speed_rotation/manifest.json'
MANIFEST_SHA256 = '97b6fb84828812ad707ec51071e57a3b02706252afe73ced75357dd748b24bd3'
SOURCE_COMMIT = 'fe0bdc001802b6cd8fd4d63eb4b0812accd72efc'
RECOVERY_SOURCE_HASHES = {
    'grip_transport_recovery_20261125.py': '208e5f378d12f7416550d14fdbdfbec927833fb8865a8c8eeec0b8ea0e3f7871',
    'serial_error_observer_20261125.py': '94d87dc9747b261c6f45584276b9030409ba8d52dab8fc6918256910646f18c1',
    'grip_pause_resume_20261125.py': 'a1d445cc8457cb0a324215c2b852f7b7984fa97069a6ff3583542885213c3dfa',
    'grip_pause_resume_10s_trial_20261125.py': '93433e0bfadc5f147721d3e943a7b9e3457d071475d853dca4be0df8248b9e02',
}
LEGACY_IMPORT_HASHES = {
    'leap_hw': 'bcac41f9ab95a406c3ad571a84c7bdb4a98ff44f420759f204b266b627c452eb',
    'limits': '4852b466d90023519fc941622ae31e20457bad8518dbb201abb934232d685299',
}
PRIMITIVES = {
    'prepare_grip_and_support': 'grip',
    'rotate_horizontal_and_support': 'horizontal',
    'rotate_vertical_and_support': 'vertical',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordedAssets:
    """Validate every bound file before importing any external controller code."""

    def __init__(self, source_root):
        self.root = Path(source_root).resolve(strict=True)
        for name, expected in LEGACY_IMPORT_HASHES.items():
            if sha(Path(__file__).parent/'recorded_compat'/(name+'.py')) != expected:
                raise ValueError('Historical import hash mismatch: '+name)
        manifest_path = self.root / MANIFEST_PATH
        if sha(manifest_path) != MANIFEST_SHA256:
            raise ValueError('Recorded manifest differs from the pinned current11/25 source version.')
        self.manifest = json.loads(manifest_path.read_bytes())
        for name, expected in self.manifest['source_hashes'].items():
            path = (self.root / name).resolve(strict=True)
            path.relative_to(self.root)
            if sha(path) != expected:
                raise ValueError('Recorded source hash mismatch: ' + name)
        for name, expected in RECOVERY_SOURCE_HASHES.items():
            if sha(self.root/name) != expected:
                raise ValueError('Recorded communication recovery source hash mismatch: '+name)
        path = manifest_path.parent / 'candidate.npz'
        if sha(path) != self.manifest['candidate_sha256']:
            raise ValueError('Recorded candidate hash mismatch.')
        with np.load(path, allow_pickle=False) as data:
            self.grip = data['start'].copy()
            goals, phases = data['goals'].copy(), data['phases'].copy()
            dense, dense_phases = data['dense_goals'].copy(), data['dense_phases'].copy()
            indices, limits = data['source_indices'].copy(), data['step_limits'].copy()
        h = self.manifest['horizontal_goals']
        dh = self.manifest['horizontal_dense_goals']
        self.goals = {'grip': np.empty((0, 16), dtype=int),
                      'horizontal': goals[:h], 'vertical': goals[h:]}
        self.phases = {'grip': [], 'horizontal': phases[:h], 'vertical': phases[h:]}
        self.dense_goals = {'grip':np.empty((0,16),dtype=int),
                            'horizontal':dense[:dh], 'vertical':dense[dh:]}
        self.source_indices = {'grip':np.empty(0,dtype=int),
                               'horizontal':indices[:h], 'vertical':indices[h:]-dh}
        self.step_limits = {'grip':np.empty(0,dtype=int),
                            'horizontal':limits[:h], 'vertical':limits[h:]}
        if (self.grip.shape != (16,) or goals.shape != (h+self.manifest['vertical_goals'], 16)
                or not np.isfinite(goals).all() or np.any(goals != np.rint(goals))
                or any(not np.array_equal(rows[-1], self.grip)
                       for rows in (self.goals['horizontal'], self.goals['vertical']))):
            raise ValueError('Recorded paths must return to the same exact G.')
        if (dense.shape != (dh+self.manifest['vertical_dense_goals'],16)
                or phases.shape != (len(goals),) or dense_phases.shape != (len(dense),)
                or indices.shape != (len(goals),) or indices.dtype.kind not in 'iu'
                or np.any(indices<0) or np.any(indices>=len(dense)) or np.any(np.diff(indices)<=0)
                or limits.shape != (len(goals),) or not np.isin(limits,[2,6]).all()
                or not np.isfinite(dense).all() or np.any(dense!=np.rint(dense))
                or not np.array_equal(goals,dense[indices])
                or not np.array_equal(phases,dense_phases[indices])
                or np.max(abs(np.diff(np.vstack([self.grip,dense]),axis=0)))>2
                or np.any(np.max(abs(np.diff(np.vstack([self.grip,goals]),axis=0)),axis=1)>limits)):
            raise ValueError('Recorded speed source proof/step limits mismatch.')
        for kind in ('horizontal','vertical'):
            proof=self.source_indices[kind]
            if proof[0]!=0 or proof[-1]!=len(self.dense_goals[kind])-1:
                raise ValueError('Recorded speed path omits its source endpoints.')

    def import_controller(self):
        # Prevent an already imported copy from redirecting ROOT-bound assets.
        for name in ('leap_measured_grip_hold_20261117', 'two_axis_cycle_plan_20261124',
                     'vertical_speed_trial_plan_20261125', 'rotation_speed_resume_plan_20261125',
                     *(Path(name).stem for name in RECOVERY_SOURCE_HASHES)):
            loaded = sys.modules.get(name)
            if loaded is not None and Path(loaded.__file__).resolve().parent != self.root:
                raise RuntimeError('Another recorded source tree is already imported; restart the node.')
        root = str(self.root)
        if root not in sys.path:
            sys.path.insert(0, root)
        # Historical source imports refer to ../work/Leap_Test/deploy, which is
        # outside the shared package. Preserve those exact two import helpers;
        # the actual motor backend remains the checked source PoseBus.
        for name, expected in LEGACY_IMPORT_HASHES.items():
            loaded = sys.modules.get(name)
            if loaded is not None:
                if sha(Path(loaded.__file__)) != expected:
                    raise RuntimeError('Conflicting historical import: '+name)
                continue
            path = Path(__file__).parent/'recorded_compat'/(name+'.py')
            if sha(path) != expected:
                raise ValueError('Historical import hash mismatch: '+name)
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(name, None)
                raise
        pose = importlib.import_module('leap_measured_grip_hold_20261117')
        plan = importlib.import_module('two_axis_cycle_plan_20261124')
        pose.validate_sources()
        return pose, plan

    def recovery_controller(self):
        self.import_controller()
        return importlib.import_module('grip_pause_resume_10s_trial_20261125')

    def speed_controller(self):
        self.import_controller()
        return importlib.import_module('vertical_speed_trial_plan_20261125')

    def summary(self):
        return dict(source_commit=SOURCE_COMMIT, source_root=str(self.root),
                    source_hashes_verified=len(self.manifest['source_hashes']),
                    candidate_sha256=self.manifest['candidate_sha256'],
                    primitive_ids=[*PRIMITIVES, FACE_UP_PRIMITIVE], devices_opened=False,
                    historical_import_hashes_verified=len(LEGACY_IMPORT_HASHES),
                    communication_recovery_sources_verified=len(RECOVERY_SOURCE_HASHES),
                    communication_recovery_maximum_extra_pause_s=10.,
                    index_then_middle_per_final_stage=True,
                    maximum_motion_step_ticks=6,
                    entry_maximum_step_ticks=2,
                    dense_source_proof_maximum_step_ticks=2,
                    arbitrary_face_orientation_mapping_available=True,
                    direction_mapping_basis='user_color_observations_20261124',
                    actual_ROS_direction_routing_tested=False)
