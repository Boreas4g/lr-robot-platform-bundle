from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="robot_decision",
                executable="book_shelf_fine_tune_node",
                name="book_shelf_fine_tune_node",
                output="screen",
                # Crash resilience: a dead fine-tune node silently breaks every
                # takeout until the whole runtime is restarted.
                respawn=True,
                respawn_delay=2.0,
                # This node has no private credentials. Keep safety-relevant
                # defaults here so its launch remains independent from the
                # Edge Gateway's node-specific parameter YAML mapping.
                parameters=[
                    {
                        "enabled": True,
                        "cmd_vel_topic": "/cmd_vel",
                        "target_frame": "map",
                        "base_frame": "base_link",
                        "control_rate_hz": 8.0,
                        "x_tolerance": 0.05,
                        "y_tolerance": 0.1,
                        "yaw_tolerance": 0.02,
                        "max_linear_speed": 0.05,
                        "max_angular_speed": 0.12,
                        "k_x": 1.0,
                        "k_y": 1.0,
                        "k_yaw": 1.0,
                        "stage_timeout_sec": 180.0,
                        "timeout_sec": 180.0,
                        # 控制逻辑与巡逻精调（point3_fine_tune_node）一致：普通精调
                        # 执行 x→y→yaw，shelf_move 只执行 x，共用 x 容差，速度可由任务覆盖。
                        # 速度直发 /cmd_vel（不经 velocity_smoother / collision_monitor）。
                        # 差速原地偏航，类阿克曼偏航由网关逐任务切换为 1m 低速圆弧。
                        # Nav2 只负责粗到点，最终精度由本节点的精调阶段保证。
                    }
                ],
            ),
        ]
    )
