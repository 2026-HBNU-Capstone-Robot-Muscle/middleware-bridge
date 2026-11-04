"""Validate and dry-run cube solutions through a ROS 2 action."""

import re
import uuid
from collections import OrderedDict
from threading import Lock

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from system_interfaces.action import ExecuteCubeSolution
from system_interfaces.msg import CubeExecutionStatus, CubeSolution


_MOVE_PATTERN = re.compile(r"^[URFDLB](?:2|')?$")
_FACES = 'URFDLB'
_MAX_SAVED_SOLUTIONS = 32


def validate_solution(solution):
    """Return an error code/message pair, or None when the solution is valid."""
    if not solution.scan_id.strip():
        return 'INVALID_SOLUTION', 'scan_id가 비어 있습니다.'

    facelets = solution.facelets
    if (len(facelets) != 54 or any(face not in _FACES for face in facelets)
            or any(facelets.count(face) != 9 for face in _FACES)):
        return 'INVALID_SOLUTION', 'facelets는 URFDLB 각 9개, 총 54자여야 합니다.'

    invalid_moves = [move for move in solution.moves if not _MOVE_PATTERN.fullmatch(move)]
    if invalid_moves:
        return 'INVALID_SOLUTION', f'허용되지 않은 이동 토큰: {invalid_moves[0]}'

    return None


class CubeSequenceExecutor(Node):
    """Expose /cube/execute_solution with hardware execution held disabled."""

    def __init__(self):
        super().__init__('cube_sequence_executor')
        status_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        solution_qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._solutions = OrderedDict()
        self._solutions_lock = Lock()
        self._status_publisher = self.create_publisher(
            CubeExecutionStatus, '/cube/execution_status', status_qos)
        self._solution_subscription = self.create_subscription(
            CubeSolution, '/cube/solution', self._on_solution, solution_qos)
        self._action_server = ActionServer(
            self,
            ExecuteCubeSolution,
            '/cube/execute_solution',
            execute_callback=self._execute,
            goal_callback=self._goal_request,
            cancel_callback=self._cancel_request,
        )
        self.get_logger().info(
            'Ready: /cube/solution -> /cube/execute_solution (dry-run only; hardware disabled)')

    @staticmethod
    def _goal_request(_goal_request):
        return GoalResponse.ACCEPT

    @staticmethod
    def _cancel_request(_goal_handle):
        return CancelResponse.ACCEPT

    def _on_solution(self, solution):
        error = validate_solution(solution)
        if error:
            code, message = error
            self._publish_status(
                solution.scan_id, '', '', CubeExecutionStatus.STATE_FAILED,
                error_code=code, message=message)
            self.get_logger().warning(f'Solution rejected: {message}')
            return

        saved = CubeSolution()
        saved.header = solution.header
        saved.scan_id = solution.scan_id
        saved.facelets = solution.facelets
        saved.moves = list(solution.moves)
        with self._solutions_lock:
            self._solutions[saved.scan_id] = saved
            self._solutions.move_to_end(saved.scan_id)
            while len(self._solutions) > _MAX_SAVED_SOLUTIONS:
                self._solutions.popitem(last=False)

        self._publish_status(
            saved.scan_id, '', '', CubeExecutionStatus.STATE_RECEIVED,
            total_moves=len(saved.moves), message='풀이를 수신하고 검증했습니다.')
        self._publish_status(
            saved.scan_id, '', '', CubeExecutionStatus.STATE_WAITING_FOR_EXECUTION,
            total_moves=len(saved.moves), message='실행 액션 목표를 기다립니다.')

    def _execute(self, goal_handle):
        goal = goal_handle.request
        result = ExecuteCubeSolution.Result()
        result.scan_id = goal.scan_id
        result.dry_run = goal.dry_run
        result.execution_id = str(uuid.uuid4())

        with self._solutions_lock:
            solution = self._solutions.get(goal.scan_id)
            if solution is not None:
                solution = self._copy_solution(solution)

        if solution is None:
            result.error_code = 'SOLUTION_NOT_FOUND'
            result.error_message = '요청한 scan_id의 검증된 풀이를 찾지 못했습니다.'
            self._finish(goal_handle, result, failed=True)
            self._publish_status(
                goal.scan_id, result.execution_id, goal.workflow_id,
                CubeExecutionStatus.STATE_FAILED, error_code=result.error_code,
                message=result.error_message)
            return result

        self._publish_status(
            goal.scan_id, result.execution_id, goal.workflow_id,
            CubeExecutionStatus.STATE_VALIDATING, total_moves=len(solution.moves),
            message='실행 목표와 저장된 풀이를 확인합니다.')
        error = validate_solution(solution)
        if error:
            result.error_code, result.error_message = error
            self._finish(goal_handle, result, failed=True)
            self._publish_status(
                goal.scan_id, result.execution_id, goal.workflow_id,
                CubeExecutionStatus.STATE_FAILED, total_moves=len(solution.moves),
                error_code=result.error_code, message=result.error_message)
            return result

        if not goal.dry_run:
            result.error_code = 'EXECUTION_DISABLED'
            result.error_message = (
                '실제 구동은 비활성화되어 있습니다. 모터 매핑, primitive 순서, 안전 조건을 '
                '확정한 뒤 구현해야 합니다.')
            self._finish(goal_handle, result, failed=True)
            self._publish_status(
                goal.scan_id, result.execution_id, goal.workflow_id,
                CubeExecutionStatus.STATE_FAILED, total_moves=len(solution.moves),
                error_code=result.error_code, message=result.error_message)
            return result

        total_moves = len(solution.moves)
        for move_index, move in enumerate(solution.moves, start=1):
            if goal_handle.is_cancel_requested:
                result.error_code = 'CANCELLED'
                result.error_message = 'dry-run 실행이 취소되었습니다.'
                self._finish(goal_handle, result, cancelled=True)
                self._publish_status(
                    goal.scan_id, result.execution_id, goal.workflow_id,
                    CubeExecutionStatus.STATE_CANCELLED, move_index=move_index,
                    total_moves=total_moves, current_move=move,
                    error_code=result.error_code, message=result.error_message)
                return result

            status = self._publish_status(
                goal.scan_id, result.execution_id, goal.workflow_id,
                CubeExecutionStatus.STATE_EXECUTING, move_index=move_index,
                total_moves=total_moves, current_move=move,
                message='이동 토큰을 dry-run으로 순회합니다. 손 primitive는 아직 전개하지 않습니다.')
            feedback = ExecuteCubeSolution.Feedback()
            feedback.status = status
            goal_handle.publish_feedback(feedback)
            result.completed_moves = move_index

        result.success = True
        result.error_code = ''
        result.error_message = (
            '입력과 solver 이동 순서를 확인했습니다. 하드웨어 구동과 hand primitive 실행은 하지 않았습니다.')
        self._finish(goal_handle, result)
        self._publish_status(
            goal.scan_id, result.execution_id, goal.workflow_id,
            CubeExecutionStatus.STATE_COMPLETED, move_index=total_moves,
            total_moves=total_moves, message=result.error_message)
        return result

    @staticmethod
    def _copy_solution(source):
        copied = CubeSolution()
        copied.header = source.header
        copied.scan_id = source.scan_id
        copied.facelets = source.facelets
        copied.moves = list(source.moves)
        return copied

    @staticmethod
    def _finish(goal_handle, result, failed=False, cancelled=False):
        if cancelled:
            goal_handle.canceled()
        elif failed:
            goal_handle.abort()
        else:
            goal_handle.succeed()

    def _publish_status(
            self, scan_id, execution_id, workflow_id, state, move_index=0,
            total_moves=0, current_move='', error_code='', message=''):
        status = CubeExecutionStatus()
        status.header.stamp = self.get_clock().now().to_msg()
        status.scan_id = scan_id
        status.execution_id = execution_id
        status.workflow_id = workflow_id
        status.state = state
        status.move_index = move_index
        status.total_moves = total_moves
        status.current_move = current_move
        status.step_index = 0
        status.total_steps = 0
        status.hand_id = ''
        status.primitive_id = ''
        status.error_code = error_code
        status.message = message
        self._status_publisher.publish(status)
        return status


def main(args=None):
    rclpy.init(args=args)
    node = CubeSequenceExecutor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
