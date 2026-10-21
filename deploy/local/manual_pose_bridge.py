#!/usr/bin/env python3
"""Manual map→odom TF bridge for local visualization and manual driving.

This is NOT AMCL. It treats the operator's initial pose (or a configured
default) as ground truth, computes map→odom from the current wheel odometry,
and broadcasts that transform at a fixed rate. It lets the map page project
the merged lidar scan onto the selected map and lets the operator drive while
seeing a dead-reckoned pose, without requiring a Nav2/AMCL installation.

Use for local bring-up only. Autonomous navigation must use the real
localization stack; this bridge does not correct drift or match scans.
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


class ManualPoseBridge(Node):
    def __init__(self) -> None:
        super().__init__("manual_pose_bridge")

        self.declare_parameter("map_frame", "map")
        self.declare_parameter("odom_frame", "odom")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("initial_pose_topic", "/initialpose")
        self.declare_parameter("publish_rate", 25.0)
        # Operator can click the robot position on the map to override this.
        self.declare_parameter("initial_x", 0.0)
        self.declare_parameter("initial_y", 0.0)
        self.declare_parameter("initial_yaw", 0.0)
        self.declare_parameter("use_default_initial_pose", True)
        # The map page's "confirm position" flow expects AMCL status/pose. In
        # this local stack there is no AMCL, so the bridge publishes the
        # operator-confirmed manual pose using the same topic contract. This is
        # a visualization/manual-drive aid, NOT real localization.
        self.declare_parameter("publish_manual_localization", True)

        self.map_frame = str(self.get_parameter("map_frame").value)
        self.odom_frame = str(self.get_parameter("odom_frame").value)
        self.odom_topic = str(self.get_parameter("odom_topic").value)
        self.initial_pose_topic = str(self.get_parameter("initial_pose_topic").value)
        rate = float(self.get_parameter("publish_rate").value)
        if rate <= 0.0:
            raise RuntimeError("publish_rate must be positive")

        self.default_pose = (
            float(self.get_parameter("initial_x").value),
            float(self.get_parameter("initial_y").value),
            float(self.get_parameter("initial_yaw").value),
        )
        self.use_default = bool(self.get_parameter("use_default_initial_pose").value)
        self.publish_manual_localization = bool(
            self.get_parameter("publish_manual_localization").value
        )

        self.latest_odom = (0.0, 0.0, 0.0)
        self.map_to_odom: tuple[float, float, float] | None = None
        self.initialized = False

        self.tf_broadcaster = TransformBroadcaster(self)
        self.amcl_pub = None
        self.status_pub = None
        self.scan_mode_pub = None
        if self.publish_manual_localization:
            self.amcl_pub = self.create_publisher(PoseWithCovarianceStamped, "/amcl_pose", 10)
            status_qos = QoSProfile(
                depth=1,
                history=HistoryPolicy.KEEP_LAST,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self.status_pub = self.create_publisher(String, "/localization/status", status_qos)
            self.scan_mode_pub = self.create_publisher(String, "/localization/scan_mode", status_qos)
            self.create_timer(1.0, self._publish_status)
            self.get_logger().warn(
                "manual localization is enabled: /localization/status and /amcl_pose are "
                "synthetic and must not be used as real AMCL output"
            )
        self.create_subscription(Odometry, self.odom_topic, self._on_odom, 10)
        self.create_subscription(
            PoseWithCovarianceStamped, self.initial_pose_topic, self._on_initial_pose, 10
        )
        self.create_timer(1.0 / rate, self._publish_tf)
        self.get_logger().info(
            f"manual pose bridge: {self.map_frame}->{self.odom_frame}, "
            f"odom={self.odom_topic}, initial_pose={self.initial_pose_topic}"
        )

    def _on_odom(self, message: Odometry) -> None:
        pose = message.pose.pose
        self.latest_odom = (
            float(pose.position.x),
            float(pose.position.y),
            yaw_from_quaternion(
                pose.orientation.x,
                pose.orientation.y,
                pose.orientation.z,
                pose.orientation.w,
            ),
        )
        if not self.initialized and self.use_default:
            self._set_map_pose(*self.default_pose, source="default")

    def _on_initial_pose(self, message: PoseWithCovarianceStamped) -> None:
        pose = message.pose.pose
        x = float(pose.position.x)
        y = float(pose.position.y)
        yaw = yaw_from_quaternion(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )
        self._set_map_pose(x, y, yaw, source="initialpose")

    def _set_map_pose(self, x: float, y: float, yaw: float, *, source: str) -> None:
        odom_x, odom_y, odom_yaw = self.latest_odom
        # map_T_odom = map_T_base * inverse(odom_T_base)
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)
        self.map_to_odom = (
            x - (cos_yaw * odom_x - sin_yaw * odom_y),
            y - (sin_yaw * odom_x + cos_yaw * odom_y),
            yaw - odom_yaw,
        )
        self.initialized = True
        self.get_logger().info(
            f"manual localization set via {source}: map pose=({x:.3f}, {y:.3f}, {yaw:.3f}), "
            f"map->odom=({self.map_to_odom[0]:.3f}, {self.map_to_odom[1]:.3f}, {self.map_to_odom[2]:.3f})"
        )

    def _current_map_pose(self) -> tuple[float, float, float] | None:
        if self.map_to_odom is None:
            return None
        ox, oy, oyaw = self.latest_odom
        mx, my, myaw = self.map_to_odom
        cos_y, sin_y = math.cos(myaw), math.sin(myaw)
        return (
            mx + cos_y * ox - sin_y * oy,
            my + sin_y * ox + cos_y * oy,
            myaw + oyaw,
        )

    def _publish_tf(self) -> None:
        if self.map_to_odom is None:
            return
        x, y, yaw = self.map_to_odom
        stamp = self.get_clock().now().to_msg()
        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = self.map_frame
        transform.child_frame_id = self.odom_frame
        transform.transform.translation.x = x
        transform.transform.translation.y = y
        transform.transform.translation.z = 0.0
        transform.transform.rotation.z = math.sin(yaw / 2.0)
        transform.transform.rotation.w = math.cos(yaw / 2.0)
        self.tf_broadcaster.sendTransform(transform)

        if self.amcl_pub is None:
            return
        pose = self._current_map_pose()
        if pose is None:
            return
        message = PoseWithCovarianceStamped()
        message.header.stamp = stamp
        message.header.frame_id = self.map_frame
        message.pose.pose.position.x = pose[0]
        message.pose.pose.position.y = pose[1]
        message.pose.pose.orientation.z = math.sin(pose[2] / 2.0)
        message.pose.pose.orientation.w = math.cos(pose[2] / 2.0)
        message.pose.covariance[0] = 0.01
        message.pose.covariance[7] = 0.01
        message.pose.covariance[35] = 0.01
        self.amcl_pub.publish(message)

    def _publish_status(self) -> None:
        if self.status_pub is None or self.scan_mode_pub is None or self.map_to_odom is None:
            return
        status = String()
        status.data = "localized"
        self.status_pub.publish(status)
        scan_mode = String()
        scan_mode.data = "dual"
        self.scan_mode_pub.publish(scan_mode)


def main() -> None:
    rclpy.init()
    node = ManualPoseBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
