"""Standard LEAP endpoint: default dry-run; explicit hardware uses recorded paths."""
from leap_hand_control.adapter_node import LeapHandAdapterNode


class LeapHandControlNode(LeapHandAdapterNode):
    def __init__(self):
        super().__init__(standard_entry=True)


def main(args=None):
    import rclpy
    rclpy.init(args=args)
    node = None
    try:
        node = LeapHandControlNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if node is not None:
                node.destroy_node()
        finally:
            rclpy.shutdown()
