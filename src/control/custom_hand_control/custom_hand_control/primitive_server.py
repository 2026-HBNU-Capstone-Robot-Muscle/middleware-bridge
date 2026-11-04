"""Dry-run-only Custom Hand action endpoint; hardware commands are disabled."""

import rclpy
import re
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.node import Node
from system_interfaces.action import ExecuteHandPrimitive


class CustomHandPrimitiveServer(Node):
    """Validate requests for the Custom Hand primitive endpoint."""

    def __init__(self):
        super().__init__('custom_hand_primitive_server')
        self._server = ActionServer(
            self,
            ExecuteHandPrimitive,
            '/custom_hand/execute_primitive',
            execute_callback=self._execute,
            goal_callback=self._goal_request,
            cancel_callback=self._cancel_request,
        )
        self.get_logger().info(
            'Ready: /custom_hand/execute_primitive (dry-run only; hardware disabled)')

    @staticmethod
    def _goal_request(_goal_request):
        return GoalResponse.ACCEPT

    @staticmethod
    def _cancel_request(_goal_handle):
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        goal = goal_handle.request
        result = ExecuteHandPrimitive.Result()
        feedback = ExecuteHandPrimitive.Feedback()
        feedback.state = feedback.STATE_ACCEPTED
        feedback.message = 'Custom Hand primitive 요청을 확인했습니다.'
        goal_handle.publish_feedback(feedback)

        if (not goal.scan_id or not goal.execution_id or not goal.primitive_id
                or goal.move_index == 0 or goal.step_index == 0
                or not re.fullmatch(r"[URFDLB](?:2|')?", goal.cube_move)):
            result.success = False
            result.error_code = 'INVALID_PRIMITIVE'
            result.error_message = (
                '식별자·1 기반 이동/단계 인덱스·유효한 cube_move·primitive_id가 필요합니다.')
            feedback.state = feedback.STATE_FAILED
            feedback.message = result.error_message
            goal_handle.publish_feedback(feedback)
            goal_handle.abort()
            return result

        if goal_handle.is_cancel_requested:
            result.error_code = 'CANCELLED'
            result.error_message = '요청이 취소되었습니다.'
            feedback.state = feedback.STATE_CANCELLED
            feedback.message = result.error_message
            goal_handle.publish_feedback(feedback)
            goal_handle.canceled()
            return result

        if not goal.dry_run:
            result.success = False
            result.error_code = 'HARDWARE_NOT_CONFIGURED'
            result.error_message = (
                'Custom Hand 손가락 정책과 Feetech 손목 제어를 연결하지 않았습니다.')
            feedback.state = feedback.STATE_FAILED
            feedback.message = result.error_message
            goal_handle.publish_feedback(feedback)
            goal_handle.abort()
            return result

        result.success = True
        result.error_code = ''
        result.error_message = 'dry-run 요청을 검증했습니다. 모터 명령은 보내지 않았습니다.'
        feedback.state = feedback.STATE_COMPLETED
        feedback.message = result.error_message
        goal_handle.publish_feedback(feedback)
        goal_handle.succeed()
        return result


def main(args=None):
    rclpy.init(args=args)
    node = CustomHandPrimitiveServer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
