"""Run device-free middleware sequencing tests and save a compact report."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest


def main():
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(
        str(root / 'tests'), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    report = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'tests': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'passed': result.wasSuccessful(),
        'ros_bindings': 'stand-ins; real executor control flow and transport wrapper tested',
        'ros_runtime_tested': False,
        'devices_opened': False,
        'physical_execution_enabled': False,
    }
    folder = root / 'results/middleware_checks'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'execution_contract.json'
    path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps(report, ensure_ascii=False))
    print(f'Report: {path}')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
