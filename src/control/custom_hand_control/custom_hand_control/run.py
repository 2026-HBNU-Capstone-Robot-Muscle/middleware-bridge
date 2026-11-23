"""Load the SHA-256 checked SB3 policy used by the hardware controller."""

import hashlib
import json
import zipfile

from .core import Fault


def inspect_policy(path):
    with zipfile.ZipFile(path) as z:
        d = json.loads(z.read('data'))
        spaces = {k: {f: d[k].get(f) for f in ('_shape', 'dtype', 'low', 'high')}
                  for k in ('observation_space', 'action_space')}
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'spaces': spaces,
            'num_timesteps': d.get('num_timesteps')}


class Policy:
    def __init__(self, path, cfg):
        digest = inspect_policy(path)['sha256']
        if digest != cfg['policy']['sha256']:
            raise Fault('Policy SHA256 mismatch or unset; inspect first')
        # Only load user-provided trusted SB3 archives: SB3 uses pickle internally.
        from stable_baselines3 import PPO
        import numpy as np
        self.np = np
        if cfg['policy'].get('format') != 'sb3':
            raise Fault('The Custom Hand hardware backend requires an SB3 policy')
        self.model = PPO.load(str(path), device='cpu')
        if self.model.observation_space.shape != (8,) or self.model.action_space.shape != (4,):
            raise Fault('Expected observation(8), action(4)')
        if not (np.all(self.model.action_space.low == -1) and np.all(self.model.action_space.high == 1)):
            raise Fault('Action bounds differ from source contract')

    def predict(self, obs):
        array = self.np.asarray(obs, dtype=self.np.float32)
        if not self.np.isfinite(array).all():
            raise Fault('Nonfinite float32 observation')
        a, _ = self.model.predict(array, deterministic=True)
        return a.tolist()
