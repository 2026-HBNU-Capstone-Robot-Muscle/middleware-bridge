"""Exercise standard startup, default dry-run, and explicit hardware admission."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import test_leap_ros_wiring as wiring
MODULE=wiring.MODULE
LeapHandPrimitiveServer=MODULE.LeapHandAdapterNode.__bases__[0]
with patch.dict(sys.modules,{'leap_hand_control.adapter_node':MODULE}):
    import leap_hand_control.control_node as CONTROL
LeapHandControlNode=CONTROL.LeapHandControlNode
ROOT=Path(__file__).resolve().parents[1]

class StartupTests(unittest.TestCase):
    def construct(self,parameters=None,legacy=False):
        values=dict(parameters or {});logs=[]
        def initialize(node):
            node.declare_parameter=lambda key,default:values.setdefault(key,default)
            node.get_parameter=lambda key:NS(value=values[key])
            node.get_logger=lambda:NS(info=logs.append,warning=logs.append)
            node.create_publisher=lambda *a,**k:NS(publish=lambda value:None)
            node.create_service=lambda *a,**k:NS()
            node.create_timer=lambda *a,**k:NS(cancel=lambda:None)
            node._policy_adapter=None;node._policy_error='test policy is absent'
        with patch.object(LeapHandPrimitiveServer,'__init__',initialize), \
                patch.object(MODULE,'Clock',lambda **kwargs:NS()):
            node=MODULE.LeapHandAdapterNode() if legacy else LeapHandControlNode()
        self.values,self.logs=values,logs
        if node._adapter is not None:self.addCleanup(node._adapter.close)
        return node

    def test_standard_default_is_original_dry_run_without_IO_timer_or_backend(self):
        with patch.object(MODULE,'DynamixelReader',side_effect=AssertionError('No devices')):
            node=self.construct()
        self.assertEqual(self.values['backend_mode'],'dry_run')
        self.assertIsNone(node._adapter)
        self.assertFalse(hasattr(node,'_io_timer'))
        self.assertTrue(any('Ready:' in s and 'dry_run' in s for s in self.logs))
        self.assertEqual(node._physical_request_error(NS())[0],'HARDWARE_DISABLED')

    def test_hardware_true_uses_recorded_backend_without_opening_devices_at_construction(self):
        node=self.construct({'hardware_enabled':True,'recorded_source_root':'C:/right/hardware/right_hand','port':'COM9'})
        backend=node._adapter.backend
        self.assertTrue(backend.recorded_mode)
        self.assertTrue(backend.armed)
        self.assertEqual(backend.expected_port,'COM9')
        self.assertEqual(backend.source_root,'C:/right/hardware/right_hand')
        self.assertIsNone(backend.thread)
        self.assertTrue(hasattr(node,'_io_timer'))
        self.assertTrue(node._accepts_primitive('rotate_horizontal_and_support'))

    def test_standard_hardware_flag_cannot_be_bypassed_with_legacy_armed_parameter(self):
        with self.assertRaisesRegex(ValueError,'hardware_enabled'):
            self.construct({'backend_mode':'recorded','recorded_source_root':'C:/source',
                            'recorded_hardware_enabled':True})

    def test_missing_source_or_conflicting_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'source root'):
            self.construct({'hardware_enabled':True})
        with self.assertRaisesRegex(ValueError,'backend_mode'):
            self.construct({'hardware_enabled':True,'backend_mode':'dry_run'})

    def test_read_only_requires_explicit_port_before_reader_is_created(self):
        with patch.object(MODULE,'DynamixelReader',side_effect=AssertionError('No devices')):
            with self.assertRaisesRegex(ValueError,'explicit port'):
                self.construct({'backend_mode':'read_only'})

    def test_explicit_mock_and_legacy_adapter_default_remain_available(self):
        for node in (self.construct({'backend_mode':'mock'}),self.construct(legacy=True)):
            self.assertTrue(node._adapter.backend.simulated)
            self.assertFalse(getattr(node._adapter.backend,'recorded_mode',False))

    def test_boolean_activation_required(self):
        with self.assertRaisesRegex(ValueError,'boolean'):
            self.construct({'hardware_enabled':'true'})

    def test_standard_console_entry_and_wrapper_target_the_same_node(self):
        setup=(ROOT/'src/control/leap_hand_control/setup.py').read_text(encoding='utf-8')
        script=(ROOT/'scripts/windows/run_leap_adapter.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('leap_hand_primitive_server = leap_hand_control.control_node:main',setup)
        self.assertIn('leap_hand_adapter = leap_hand_control.adapter_node:main',setup)
        self.assertIn('hardware_enabled:=true',script)
        self.assertIn('leap_hand_control leap_hand_primitive_server',script)

    def test_standard_main_closes_node_and_ROS_after_interrupt(self):
        events=[]
        def interrupt(node):
            events.append('spin');raise KeyboardInterrupt()
        fake=NS(init=lambda **k:events.append('init'),spin=interrupt,
                shutdown=lambda:events.append('shutdown'))
        node=NS(destroy_node=lambda:events.append('destroy'))
        with patch.dict(sys.modules,{'rclpy':fake}),patch.object(CONTROL,'LeapHandControlNode',return_value=node):
            CONTROL.main()
        self.assertEqual(events,['init','spin','destroy','shutdown'])

    def test_standard_main_shuts_ROS_down_when_startup_is_rejected(self):
        events=[]
        fake=NS(init=lambda **k:events.append('init'),shutdown=lambda:events.append('shutdown'))
        with patch.dict(sys.modules,{'rclpy':fake}),patch.object(CONTROL,'LeapHandControlNode',side_effect=ValueError('invalid configuration')):
            with self.assertRaisesRegex(ValueError,'invalid configuration'):CONTROL.main()
        self.assertEqual(events,['init','shutdown'])

    def test_shutdown_failure_is_reported_and_does_not_skip_ROS_shutdown(self):
        events=[]
        def fail():
            events.append('destroy');raise RuntimeError('STOP_UNCONFIRMED')
        fake=NS(init=lambda **k:None,spin=lambda node:None,
                shutdown=lambda:events.append('shutdown'))
        with patch.dict(sys.modules,{'rclpy':fake}),patch.object(CONTROL,'LeapHandControlNode',return_value=NS(destroy_node=fail)):
            with self.assertRaisesRegex(RuntimeError,'STOP_UNCONFIRMED'):CONTROL.main()
        self.assertEqual(events,['destroy','shutdown'])

class DefaultActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_standard_dry_run_uses_existing_callback_without_opening_a_backend(self):
        node=object.__new__(LeapHandControlNode);node._adapter=None
        _,goal,terminal=wiring.WiringTests().setup_node()
        result=await node._execute_validated(goal,wiring.Result(),wiring.Feedback())
        self.assertTrue(result.success)
        self.assertEqual(terminal,['success'])
        self.assertIsNone(node._adapter)

if __name__=='__main__':unittest.main()
