"""Replay a saved CubeSolution and check success, cancellation, or rejection."""

import argparse
import json
import re
import time
import uuid
from collections import Counter
from pathlib import Path

import rclpy
from action_msgs.msg import GoalStatus
from rclpy.action import ActionClient
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from system_interfaces.action import ExecuteCubeSolution
from system_interfaces.msg import CubeExecutionStatus, CubeSolution
from system_interfaces.srv import SolveCube

MOVE_PATTERN = re.compile(r"^[URFDLB](?:2|')?$")
FACE_SYMBOLS = set('URFDLB')


def latest_solution_path():
    """Find the newest saved camera solution in the workspace."""
    root = Path(__file__).resolve().parents[1]
    paths = list((root / 'results' / 'cube_solutions').glob('*.json'))
    if not paths:
        raise FileNotFoundError('results/cube_solutions에 JSON 풀이가 없습니다.')
    return max(paths, key=lambda path: path.stat().st_mtime)


def validate_solution_document(document):
    """Reject malformed or internally inconsistent saved solution JSON."""
    if not isinstance(document, dict):
        raise ValueError('JSON 최상위 값은 object여야 합니다.')
    if document.get('format') != 'Kociemba URFDLB':
        raise ValueError("format은 'Kociemba URFDLB'여야 합니다.")
    if not isinstance(document.get('scan_id'), str) or not document['scan_id'].strip():
        raise ValueError('scan_id는 비어 있지 않은 문자열이어야 합니다.')

    facelets = document.get('facelets')
    if (not isinstance(facelets, str) or len(facelets) != 54
            or any(symbol not in FACE_SYMBOLS for symbol in facelets)):
        raise ValueError('facelets는 URFDLB로만 구성된 54자여야 합니다.')
    counts = Counter(facelets)
    wrong_counts = {
        face: counts.get(face, 0) for face in 'URFDLB'
        if counts.get(face, 0) != 9
    }
    if wrong_counts:
        details = ', '.join(f'{face}={count}' for face, count in wrong_counts.items())
        raise ValueError(f'각 면 문자는 9회여야 합니다: {details}')

    moves = document.get('moves')
    if (not isinstance(moves, list) or not moves
            or any(not isinstance(move, str) or not MOVE_PATTERN.fullmatch(move)
                   for move in moves)):
        raise ValueError("moves에는 U/R/F/D/L/B와 선택적 ' 또는 2 토큰만 올 수 있습니다.")
    move_count = document.get('move_count')
    if type(move_count) is not int or move_count != len(moves):
        raise ValueError(
            f'move_count({move_count})가 moves 길이({len(moves)})와 일치해야 합니다.')


def main():
    """Publish a saved solution and validate the selected dry-run path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--mode', choices=('success', 'cancel', 'missing'), default='success',
        help='성공, 실행 중 취소, 존재하지 않는 scan_id 거부 중 확인할 경로')
    parser.add_argument(
        '--solution', type=Path, default=None,
        help='재생할 JSON 경로. 기본값은 가장 최근 저장 풀이')
    parser.add_argument(
        '--validate-only', action='store_true',
        help='ROS에 발행하지 않고 JSON 파일 형식만 검사')
    args = parser.parse_args()
    try:
        solution_path = (args.solution or latest_solution_path()).resolve(strict=True)
        if not solution_path.is_file():
            raise ValueError('선택한 경로가 파일이 아닙니다.')
        document = json.loads(solution_path.read_text(encoding='utf-8-sig'))
        validate_solution_document(document)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f'입력 JSON 검증 실패: {exc}')
        return 2

    print(f'solution_file: {solution_path}')
    print(f'source_scan_id: {document["scan_id"]}')
    print(f'move_count: {document["move_count"]}')
    if args.validate_only:
        print('validation: PASS')
        return 0

    rclpy.init()
    node = rclpy.create_node('saved_solution_dryrun_check')
    solver_client = node.create_client(SolveCube, '/cube/solve')
    publisher = None
    client = None
    try:
        if not solver_client.wait_for_service(timeout_sec=10.0):
            raise RuntimeError(
                '/cube/solve 서비스를 찾을 수 없어 물리 상태 검증을 할 수 없습니다.')
        request = SolveCube.Request()
        request.facelets = document['facelets']
        solve_future = solver_client.call_async(request)
        rclpy.spin_until_future_complete(node, solve_future, timeout_sec=10.0)
        if not solve_future.done():
            raise TimeoutError('/cube/solve 응답 대기 시간이 초과됐습니다.')
        solve_response = solve_future.result()
        if solve_response is None or not solve_response.success:
            reason = (solve_response.error_message if solve_response is not None
                      else '서비스 응답을 받지 못했습니다.')
            raise ValueError(f'cube_solver가 facelet 상태를 거부했습니다: {reason}')
        print('solver_validation: PASS')

        qos = QoSProfile(
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        publisher = node.create_publisher(CubeSolution, '/cube/solution', qos)
        client = ActionClient(
            node, ExecuteCubeSolution, '/cube/execute_solution')
        if not client.wait_for_server(timeout_sec=10.0):
            raise RuntimeError('/cube/execute_solution 서버를 찾을 수 없습니다.')

        message = CubeSolution()
        message.scan_id = document['scan_id']
        message.facelets = document['facelets']
        message.moves = list(document['moves'])

        if args.mode == 'missing':
            scan_id = 'missing-' + uuid.uuid4().hex
        else:
            scan_id = message.scan_id + '-' + args.mode + '-' + uuid.uuid4().hex[:8]
            message.scan_id = scan_id
            publisher.publish(message)
            time.sleep(0.5)

        goal = ExecuteCubeSolution.Goal()
        goal.scan_id = scan_id
        goal.workflow_id = 'two_hand_layer_turn_v1'
        goal.dry_run = True
        goal.run_pretrained_policies = False

        feedback_states = []

        def on_feedback(feedback_message):
            feedback_states.append(feedback_message.feedback.status.state)

        goal_future = client.send_goal_async(
            goal, feedback_callback=on_feedback)
        rclpy.spin_until_future_complete(node, goal_future, timeout_sec=10.0)
        if not goal_future.done():
            raise TimeoutError('action goal 수락 대기 시간이 초과됐습니다.')
        goal_handle = goal_future.result()
        if not goal_handle.accepted:
            raise RuntimeError('action goal이 거부됐습니다.')

        result_future = goal_handle.get_result_async()
        cancel_sent = False
        deadline = time.monotonic() + 60.0
        while not result_future.done() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.05)
            if (args.mode == 'cancel' and not cancel_sent
                    and CubeExecutionStatus.STATE_EXECUTING in feedback_states):
                goal_handle.cancel_goal_async()
                cancel_sent = True

        if not result_future.done():
            raise TimeoutError('action result 대기 시간이 초과됐습니다.')
        wrapped = result_future.result()
        result = wrapped.result
        status_names = {
            GoalStatus.STATUS_SUCCEEDED: 'SUCCEEDED',
            GoalStatus.STATUS_CANCELED: 'CANCELED',
            GoalStatus.STATUS_ABORTED: 'ABORTED',
        }
        print(f'mode: {args.mode}')
        print(f'scan_id: {scan_id}')
        status_name = status_names.get(wrapped.status, 'UNKNOWN')
        print(f'terminal_status: {status_name} ({wrapped.status})')
        print(f'success: {result.success}')
        print(f'completed_moves: {result.completed_moves}')
        print(f'completed_steps: {result.completed_steps}')
        print(f'error_code: {result.error_code}')
        print(f'error_message: {result.error_message}')

        if args.mode == 'success':
            expected = (result.success
                        and result.completed_moves == len(message.moves)
                        and result.completed_steps == 4 * len(message.moves))
        elif args.mode == 'cancel':
            expected = (cancel_sent
                        and wrapped.status == GoalStatus.STATUS_CANCELED
                        and result.error_code == 'CANCELLED')
        else:
            expected = (wrapped.status == GoalStatus.STATUS_ABORTED
                        and result.error_code == 'SOLUTION_NOT_FOUND')
        print(f'check: {"PASS" if expected else "FAIL"}')
        return 0 if expected else 1
    except (RuntimeError, TimeoutError, ValueError) as exc:
        print(f'ROS 검증 실패: {exc}')
        return 2
    finally:
        if client is not None:
            client.destroy()
        solver_client.destroy()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    raise SystemExit(main())
