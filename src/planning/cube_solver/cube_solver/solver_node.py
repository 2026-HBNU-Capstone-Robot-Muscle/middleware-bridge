"""ROS 2 service wrapper for the Kociemba two-phase cube solver."""

import rclpy
from rclpy.node import Node
from system_interfaces.srv import SolveCube


class CubeSolverNode(Node):
    """Validate a facelet string and return a Kociemba move sequence."""

    def __init__(self):
        super().__init__('cube_solver')
        self.declare_parameter('service_name', '/cube/solve')

        try:
            from rubik_solver import Cube, init_solver, solve
        except ImportError as exc:
            raise RuntimeError(
                'rubik-solver-py is missing. Install the Pixi project dependencies.'
            ) from exc
        init_solver()
        self._cube_type = Cube
        self._solve = solve
        service_name = str(self.get_parameter('service_name').value)
        self.service = self.create_service(
            SolveCube, service_name, self._handle_solve
        )
        self.get_logger().info(f'Cube solver service ready: {service_name}')

    def _handle_solve(self, request, response):
        facelets = request.facelets
        if len(facelets) != 54:
            response.success = False
            response.error_message = (
                f'Expected exactly 54 facelets; received {len(facelets)}.'
            )
            return response

        if set(facelets) - set('URFDLB'):
            response.success = False
            response.error_message = (
                'Facelets may contain only U, R, F, D, L, and B.'
            )
            return response

        if any(facelets.count(face) != 9 for face in 'URFDLB'):
            response.success = False
            response.error_message = (
                'Each face label U, R, F, D, L, and B must occur exactly 9 times.'
            )
            return response

        solved_facelets = ''.join(face * 9 for face in 'URFDLB')
        if facelets == solved_facelets:
            response.success = True
            response.moves = []
            response.error_message = ''
            return response

        try:
            cube = self._cube_type.from_string(facelets)
            if cube.verify() is not True:
                raise ValueError('Kociemba rejected the cube state.')
            solution = self._solve(cube, max_depth=20)
            if solution is None:
                raise ValueError('No solution found within 20 moves.')
        except Exception as exc:
            response.success = False
            response.error_message = f'Cube state is invalid or unsolvable: {exc}'
            return response

        raw_moves = solution.split() if isinstance(solution, str) else solution
        moves = [str(move).strip().upper() for move in raw_moves]
        allowed_moves = {
            face + suffix
            for face in 'URFDLB'
            for suffix in ('', "'", '2')
        }
        if any(move not in allowed_moves for move in moves):
            response.success = False
            response.error_message = 'Solver returned an unsupported move token.'
            return response

        response.success = True
        response.moves = moves
        response.error_message = ''
        return response


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = CubeSolverNode()
        rclpy.spin(node)
    except RuntimeError as exc:
        print(f'cube_solver: {exc}')
        return 2
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0
