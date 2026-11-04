"""Validate cube solutions and run their two-hand workflow in dry-run mode."""

import re
import uuid
from collections import OrderedDict
from threading import Lock

import rclpy
from rclpy.action import (
    ActionClient,
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from cube_execution.calibration import validate_calibration_file
from system_interfaces.action import ExecuteCubeSolution, ExecuteHandPrimitive
from system_interfaces.msg import CubeExecutionStatus, CubeSolution


_MOVE_PATTERN = re.compile(r"^[URFDLB](?:2|')?$")
_FACES = 'URFDLB'
_MAX_SAVED_SOLUTIONS = 32
_WORKFLOW_ID = 'two_hand_layer_turn_v1'


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


def compile_workflow(moves):
    """Expand each Kociemba token into semantic LEAP and Custom Hand steps.

    The target face stays in Kociemba's logical URFDLB frame. A hand adapter
    must combine it with measured cube pose before issuing physical commands.
    """
    plan = []
    for move_index, move in enumerate(moves, start=1):
        target_face = move[0]
        suffix = move[1:]
        turns = 2 if suffix == '2' else -1 if suffix == "'" else 1
        plan.extend([
            {
                'move_index': move_index,
                'cube_move': move,
                'target_face': target_face,
                'clockwise_quarter_turns': 0,
                'hand_id': 'leap_hand',
                'primitive_id': 'orient_face_up_and_support',
            },
            {
                'move_index': move_index,
                'cube_move': move,
                'target_face': target_face,
                'clockwise_quarter_turns': 0,
                'hand_id': 'custom_hand',
                'primitive_id': 'grasp_upper_layer',
            },
            {
                'move_index': move_index,
                'cube_move': move,
                'target_face': target_face,
                'clockwise_quarter_turns': turns,
                'hand_id': 'custom_hand',
                'primitive_id': 'rotate_upper_layer',
            },
            {
                'move_index': move_index,
                'cube_move': move,
                'target_face': target_face,
                'clockwise_quarter_turns': 0,
                'hand_id': 'custom_hand',
                'primitive_id': 'release_upper_layer',
            },
        ])
    return plan


class CubeSequenceExecutor(Node):
    """Run the declared workflow while keeping physical motion disabled."""

    def __init__(self):
        super().__init__('cube_sequence_executor')
        self._callback_group = ReentrantCallbackGroup()
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
        self._execution_busy = False
        self._execution_busy_lock = Lock()
        self._active_goal_handle = None
        self.declare_parameter('calibration_file', '')
        calibration_file = self.get_parameter('calibration_file').value
        self._calibration_errors = validate_calibration_file(calibration_file)
        if self._calibration_errors:
            self.get_logger().warning(
                'Physical calibration gate is closed: '
                + '; '.join(self._calibration_errors[:5]))
        self._status_publisher = self.create_publisher(
            CubeExecutionStatus, '/cube/execution_status', status_qos)
        self._solution_subscription = self.create_subscription(
            CubeSolution, '/cube/solution', self._on_solution, solution_qos)
        self._hand_clients = {
            'leap_hand': ActionClient(
                self, ExecuteHandPrimitive, '/leap_hand/execute_primitive',
                callback_group=self._callback_group),
            'custom_hand': ActionClient(
                self, ExecuteHandPrimitive, '/custom_hand/execute_primitive',
                callback_group=self._callback_group),
        }
        self._action_server = ActionServer(
            self,
            ExecuteCubeSolution,
            '/cube/execute_solution',
            execute_callback=self._execute,
            goal_callback=self._goal_request,
            cancel_callback=self._cancel_request,
            callback_group=self._callback_group,
        )
        self.get_logger().info(
            'Ready: /cube/execute_solution; dry-run dispatches semantic steps to both hand endpoints')

    def _goal_request(self, _goal_request):
        with self._execution_busy_lock:
            if self._execution_busy:
                return GoalResponse.REJECT
            self._execution_busy = True
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

        saved = self._copy_solution(solution)
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

    async def _execute(self, goal_handle):
        self._active_goal_handle = goal_handle
        try:
            return await self._execute_goal(goal_handle)
        finally:
            self._active_goal_handle = None
            with self._execution_busy_lock:
                self._execution_busy = False

    async def _execute_goal(self, goal_handle):
        goal = goal_handle.request
        result = ExecuteCubeSolution.Result()
        result.scan_id = goal.scan_id
        result.dry_run = goal.dry_run
        result.execution_id = str(uuid.uuid4())
        workflow_id = goal.workflow_id.strip() or _WORKFLOW_ID

        with self._solutions_lock:
            saved = self._solutions.get(goal.scan_id)
            solution = self._copy_solution(saved) if saved is not None else None

        if solution is None:
            return self._fail(
                goal_handle, result, workflow_id, 'SOLUTION_NOT_FOUND',
                '요청한 scan_id의 검증된 풀이를 찾지 못했습니다.')

        self._publish_status(
            goal.scan_id, result.execution_id, workflow_id,
            CubeExecutionStatus.STATE_VALIDATING, total_moves=len(solution.moves),
            message='실행 목표와 저장된 풀이를 확인합니다.')
        error = validate_solution(solution)
        if error:
            return self._fail(goal_handle, result, workflow_id, *error,
                              total_moves=len(solution.moves))

        if workflow_id != _WORKFLOW_ID:
            return self._fail(
                goal_handle, result, workflow_id, 'WORKFLOW_NOT_FOUND',
                f'지원하지 않는 workflow_id입니다. 사용 가능 값: {_WORKFLOW_ID}',
                total_moves=len(solution.moves))

        if not goal.dry_run:
            if self._calibration_errors:
                return self._fail(
                    goal_handle, result, workflow_id, 'CALIBRATION_INCOMPLETE',
                    '실제 구동 calibration 검증이 완료되지 않았습니다: '
                    + '; '.join(self._calibration_errors))
            return self._fail(
                goal_handle, result, workflow_id, 'EXECUTION_DISABLED',
                'calibration 기록은 통과했지만 실제 모터 드라이버와 안전 정지 adapter는 아직 구현되지 않았습니다.',
                total_moves=len(solution.moves))

        plan = compile_workflow(solution.moves)
        result.completed_steps = 0
        result.completed_moves = 0
        total_moves = len(solution.moves)
        total_steps = len(plan)
        previous_hand = ''

        for step_index, step in enumerate(plan, start=1):
            if goal_handle.is_cancel_requested:
                result.error_code = 'CANCELLED'
                result.error_message = '실행이 hand primitive 경계에서 취소되었습니다.'
                goal_handle.canceled()
                self._publish_status(
                    goal.scan_id, result.execution_id, workflow_id,
                    CubeExecutionStatus.STATE_CANCELLED,
                    move_index=step['move_index'], total_moves=total_moves,
                    current_move=step['cube_move'], step_index=step_index - 1,
                    total_steps=total_steps, error_code=result.error_code,
                    message=result.error_message)
                return result

            if previous_hand and previous_hand != step['hand_id']:
                handoff_status = self._publish_status(
                    goal.scan_id, result.execution_id, workflow_id,
                    CubeExecutionStatus.STATE_HANDOFF,
                    move_index=step['move_index'], total_moves=total_moves,
                    current_move=step['cube_move'], step_index=step_index,
                    total_steps=total_steps, hand_id='', primitive_id='',
                    message=f"{previous_hand}에서 {step['hand_id']}로 handoff합니다.")
                self._publish_feedback(goal_handle, handoff_status)

            status = self._publish_status(
                goal.scan_id, result.execution_id, workflow_id,
                CubeExecutionStatus.STATE_EXECUTING,
                move_index=step['move_index'], total_moves=total_moves,
                current_move=step['cube_move'], step_index=step_index,
                total_steps=total_steps, hand_id=step['hand_id'],
                primitive_id=step['primitive_id'],
                message='hand primitive dry-run을 실행합니다. 모터 명령은 비활성화되어 있습니다.')
            self._publish_feedback(goal_handle, status)

            hand_result, error_message = await self._dispatch_step(
                goal_handle, goal, result, step_index, step)
            if hand_result is None or not hand_result.success:
                if goal_handle.is_cancel_requested:
                    result.success = False
                    result.error_code = 'CANCELLED'
                    result.error_message = '실행이 hand primitive 경계에서 취소되었습니다.'
                    goal_handle.canceled()
                    self._publish_status(
                        goal.scan_id, result.execution_id, workflow_id,
                        CubeExecutionStatus.STATE_CANCELLED,
                        move_index=step['move_index'], total_moves=total_moves,
                        current_move=step['cube_move'], step_index=step_index,
                        total_steps=total_steps, hand_id=step['hand_id'],
                        primitive_id=step['primitive_id'],
                        error_code=result.error_code,
                        message=result.error_message)
                    return result
                error_code = (
                    hand_result.error_code if hand_result is not None
                    else 'HAND_NOT_READY')
                message = (
                    hand_result.error_message if hand_result is not None
                    else error_message)
                return self._fail(
                    goal_handle, result, workflow_id, error_code, message,
                    move_index=step['move_index'], total_moves=total_moves,
                    current_move=step['cube_move'], step_index=step_index,
                    total_steps=total_steps, hand_id=step['hand_id'],
                    primitive_id=step['primitive_id'])

            result.completed_steps = step_index
            if step['primitive_id'] == 'rotate_upper_layer':
                result.completed_moves = step['move_index']
            previous_hand = step['hand_id']

        result.success = True
        result.error_code = ''
        result.error_message = (
            '풀이를 hand primitive 단계로 전개하고 두 adapter의 dry-run 응답을 확인했습니다. '
            '물리 동작은 하지 않았습니다.')
        goal_handle.succeed()
        final_status = self._publish_status(
            goal.scan_id, result.execution_id, workflow_id,
            CubeExecutionStatus.STATE_COMPLETED, move_index=total_moves,
            total_moves=total_moves, step_index=total_steps,
            total_steps=total_steps, message=result.error_message)
        self._publish_feedback(goal_handle, final_status)
        return result

    async def _dispatch_step(
            self, parent_goal_handle, parent_goal, parent_result, step_index, step):
        client = self._hand_clients[step['hand_id']]
        if not client.wait_for_server(timeout_sec=0.5):
            return None, f"{step['hand_id']} action server에 연결할 수 없습니다."

        request = ExecuteHandPrimitive.Goal()
        request.scan_id = parent_goal.scan_id
        request.execution_id = parent_result.execution_id
        request.move_index = step['move_index']
        request.step_index = step_index
        request.cube_move = step['cube_move']
        request.target_face = step['target_face']
        request.clockwise_quarter_turns = step['clockwise_quarter_turns']
        request.primitive_id = step['primitive_id']
        request.dry_run = True

        try:
            child_goal = await client.send_goal_async(request)
            if not child_goal.accepted:
                return None, f"{step['hand_id']}가 primitive 요청을 거부했습니다."

            result_future = child_goal.get_result_async()
            cancellation = {'sent': False}

            def cancel_child_if_requested():
                if parent_goal_handle.is_cancel_requested and not cancellation['sent']:
                    cancellation['sent'] = True
                    child_goal.cancel_goal_async()

            cancel_timer = self.create_timer(
                0.05, cancel_child_if_requested, callback_group=self._callback_group)
            try:
                wrapped_result = await result_future
            finally:
                cancel_timer.cancel()
                self.destroy_timer(cancel_timer)
            return wrapped_result.result, ''
        except Exception as exc:  # ROS action transport errors become action results.
            return None, f"{step['hand_id']} action 오류: {exc}"

    def _fail(
            self, goal_handle, result, workflow_id, error_code, message,
            move_index=0, total_moves=0, current_move='', step_index=0,
            total_steps=0, hand_id='', primitive_id=''):
        result.success = False
        result.error_code = error_code
        result.error_message = message
        goal_handle.abort()
        status = self._publish_status(
            result.scan_id, result.execution_id, workflow_id,
            CubeExecutionStatus.STATE_FAILED, move_index=move_index,
            total_moves=total_moves, current_move=current_move,
            step_index=step_index, total_steps=total_steps,
            hand_id=hand_id, primitive_id=primitive_id,
            error_code=error_code, message=message)
        self._publish_feedback(goal_handle, status)
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
    def _publish_feedback(goal_handle, status):
        feedback = ExecuteCubeSolution.Feedback()
        feedback.status = status
        goal_handle.publish_feedback(feedback)

    def _publish_status(
            self, scan_id, execution_id, workflow_id, state, move_index=0,
            total_moves=0, current_move='', step_index=0, total_steps=0,
            hand_id='', primitive_id='', error_code='', message=''):
        status = CubeExecutionStatus()
        status.header.stamp = self.get_clock().now().to_msg()
        status.scan_id = scan_id
        status.execution_id = execution_id
        status.workflow_id = workflow_id
        status.state = state
        status.move_index = move_index
        status.total_moves = total_moves
        status.current_move = current_move
        status.step_index = step_index
        status.total_steps = total_steps
        status.hand_id = hand_id
        status.primitive_id = primitive_id
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
