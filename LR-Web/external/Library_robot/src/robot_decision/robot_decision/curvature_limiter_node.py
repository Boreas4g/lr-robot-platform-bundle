from __future__ import annotations

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from robot_decision.drive_control import ACKERMANN, DIFFERENTIAL, constrain_ackermann_velocity


class CurvatureLimiterNode(Node):
    def __init__(self) -> None:
        super().__init__("curvature_limiter")
        self.declare_parameter("input_topic", "/cmd_vel_nav")
        self.declare_parameter("output_topic", "/cmd_vel_limited")
        self.declare_parameter("control_mode_topic", "/navigation/control_mode")
        self.declare_parameter("min_turning_radius", 1.0)
        self.declare_parameter("min_turn_linear_speed", 0.08)
        self._control_mode = DIFFERENTIAL
        self._min_turning_radius = float(self.get_parameter("min_turning_radius").value)
        self._min_turn_linear_speed = float(self.get_parameter("min_turn_linear_speed").value)
        if self._min_turning_radius <= 0.0 or self._min_turn_linear_speed <= 0.0:
            raise ValueError("curvature limits must be positive")
        self._publisher = self.create_publisher(
            Twist, str(self.get_parameter("output_topic").value), 10
        )
        self.create_subscription(
            Twist,
            str(self.get_parameter("input_topic").value),
            self._limit_velocity,
            10,
        )
        self.create_subscription(
            String,
            str(self.get_parameter("control_mode_topic").value),
            self._set_control_mode,
            QoSProfile(
                depth=1,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                reliability=ReliabilityPolicy.RELIABLE,
            ),
        )

    def _set_control_mode(self, message: String) -> None:
        if message.data in {DIFFERENTIAL, ACKERMANN}:
            self._control_mode = message.data

    def _limit_velocity(self, message: Twist) -> None:
        if self._control_mode == ACKERMANN:
            message.linear.x, message.angular.z = constrain_ackermann_velocity(
                message.linear.x,
                message.angular.z,
                self._min_turning_radius,
                self._min_turn_linear_speed,
            )
        self._publisher.publish(message)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = CurvatureLimiterNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
