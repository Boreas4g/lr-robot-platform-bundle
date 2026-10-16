/**
 * base_controller_node.cpp
 *
 * C++ ROS node for DDSM115 4WD base controller.
 *
 * Architecture:
 *  - cmd_vel callback:  stores velocity command, signals TX thread
 *  - TX thread:         converts cmd to RPM, sends to all 4 motors with
 *                       inter-command gap to prevent RS485 bus collisions
 *  - Feedback thread:   polls motor feedback at fixed rate, publishes odometry
 *  - bus_mutex_:        ensures TX and feedback never overlap on the serial bus
 */

#include <ros/ros.h>
#include <geometry_msgs/Twist.h>
#include <nav_msgs/Odometry.h>
#include <std_msgs/Float32MultiArray.h>
#include <tf/transform_broadcaster.h>

#include <serial/serial.h>
#include <linux/serial.h>
#include <sys/ioctl.h>
#include <fcntl.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cmath>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "robot_4wd_dds115_base_controller/ddsm115_protocol.hpp"

// Resolve symlinks to canonical path (e.g. /dev/rs485 -> /dev/ttyUSB0)
static std::string canonicalPath(const std::string& path)
{
    char resolved[256] = {};
    // First: resolve the device symlink itself
    ssize_t len = readlink(path.c_str(), resolved, sizeof(resolved) - 1);
    if (len > 0) {
        std::string r(resolved, static_cast<size_t>(len));
        if (r[0] != '/') r = "/dev/" + r;  // relative symlink → absolute
        return r;
    }
    return path;  // not a symlink, use as-is
}

// Find the file descriptor that serial::Serial opened for a given device path
static int getFdForDevice(const std::string& port)
{
    std::string target = canonicalPath(port);
    char path[64], link[256];
    for (int fd = 3; fd < 256; fd++) {
        snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
        ssize_t len = readlink(path, link, sizeof(link) - 1);
        if (len > 0 && target == std::string(link, static_cast<size_t>(len)))
            return fd;
    }
    return -1;
}

static void enableRS485Mode(const std::string& port)
{
    int fd = getFdForDevice(port);
    if (fd < 0) {
        ROS_WARN("RS485: could not find fd for %s — skipping", port.c_str());
        return;
    }
    struct serial_rs485 rs485;
    memset(&rs485, 0, sizeof(rs485));
    rs485.flags             = SER_RS485_ENABLED | SER_RS485_RTS_ON_SEND;
    rs485.delay_rts_before_send = 0;
    rs485.delay_rts_after_send  = 0;
    if (ioctl(fd, TIOCSRS485, &rs485) < 0)
        ROS_INFO("RS485 kernel ioctl not supported (USB adapter handles direction in hardware)");
    else
        ROS_INFO("RS485 kernel mode enabled on fd %d", fd);
}

class BaseControllerNode
{
public:
    BaseControllerNode() : pnh_("~"), running_(false)
    {
        // ── Parameters ───────────────────────────────────────────────────────
        std::string device;
        pnh_.param<std::string>("device_path",    device,            "/dev/rs485");
        pnh_.param<double>("wheel_radius",        wheel_radius_,     0.05);
        pnh_.param<double>("wheel_track",         wheel_track_,      0.33);
        pnh_.param<double>("wheel_base",          wheel_base_,       0.33);
        pnh_.param<double>("feedback_rate_hz",    feedback_rate_hz_, 10.0);
        pnh_.param<double>("cmd_vel_timeout",     cmd_vel_timeout_,   1.0);
        pnh_.param<int>   ("inter_cmd_gap_ms",    inter_cmd_gap_ms_,  4);
        pnh_.param<double>("accel_rpm_per_sec",   accel_rpm_per_sec_, 400.0);

        pnh_.param("wheel_ids",        wheel_ids_,        std::vector<int>{1, 2, 3, 4});
        pnh_.param("wheel_directions", wheel_directions_,
                   std::vector<std::string>{"forward", "backward", "forward", "backward"});

        // ── Serial port ───────────────────────────────────────────────────────
        try {
            serial_.setPort(device);
            serial_.setBaudrate(115200);
            serial::Timeout to = serial::Timeout::simpleTimeout(50);  // 50ms read timeout
            serial_.setTimeout(to);
            serial_.open();
        } catch (const serial::IOException& e) {
            ROS_FATAL("Failed to open serial port %s: %s", device.c_str(), e.what());
            ros::shutdown();
            return;
        }
        ROS_INFO("Opened serial port: %s", device.c_str());

        // ── Enable kernel RS485 mode (RTS controls TX/RX direction) ──────────
        enableRS485Mode(device);

        // ── Set all motors to velocity mode ──────────────────────────────────
        for (int id : wheel_ids_) {
            auto frame = ddsm115::buildDriveModeFrame(
                static_cast<uint8_t>(id), ddsm115::DriveMode::VELOCITY);
            serial_.write(frame.data(), frame.size());
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
            serial_.flushInput();
            ROS_INFO("Motor %d set to velocity mode", id);
        }

        // ── ROS interfaces ────────────────────────────────────────────────────
        cmd_vel_sub_  = nh_.subscribe("cmd_vel",      10,
                                      &BaseControllerNode::cmdVelCallback, this);
        odom_pub_     = nh_.advertise<nav_msgs::Odometry>("wheel_odom", 10);
        rpm_pub_      = nh_.advertise<std_msgs::Float32MultiArray>("motor_rpms", 10);
        current_pub_  = nh_.advertise<std_msgs::Float32MultiArray>("motor_currents", 10);

        // ── Init state ────────────────────────────────────────────────────────
        motor_rpms_.fill(0);
        motor_currents_.fill(0.0f);
        last_cmd_time_ = ros::Time::now();
        last_odom_time_ = ros::Time::now();

        // ── Init ramp state ───────────────────────────────────────────────────
        current_cmd_rpms_.fill(0.0);
        last_tx_time_ = std::chrono::steady_clock::now();

        // ── Start worker threads ──────────────────────────────────────────────
        running_ = true;
        tx_thread_       = std::thread(&BaseControllerNode::txThreadFunc, this);
        feedback_thread_ = std::thread(&BaseControllerNode::feedbackThreadFunc, this);

        ROS_INFO("Base controller ready.");
    }

    ~BaseControllerNode()
    {
        running_ = false;
        cmd_cv_.notify_all();
        if (tx_thread_.joinable())       tx_thread_.join();
        if (feedback_thread_.joinable()) feedback_thread_.join();

        // Stop all motors before exit
        if (serial_.isOpen()) {
            std::lock_guard<std::mutex> lock(bus_mutex_);
            for (int id : wheel_ids_) {
                auto frame = ddsm115::buildRpmFrame(static_cast<uint8_t>(id), 0);
                serial_.write(frame.data(), frame.size());
                std::this_thread::sleep_for(
                    std::chrono::milliseconds(inter_cmd_gap_ms_));
                serial_.flushInput();
            }
            serial_.close();
        }
    }

    void spin() { ros::spin(); }

private:
    // ── cmd_vel callback ─────────────────────────────────────────────────────
    void cmdVelCallback(const geometry_msgs::Twist::ConstPtr& msg)
    {
        {
            std::lock_guard<std::mutex> lock(cmd_mutex_);
            cmd_linear_  = msg->linear.x;
            cmd_angular_ = msg->angular.z;
            cmd_updated_ = true;
            last_cmd_time_ = ros::Time::now();
        }
        cmd_cv_.notify_one();
    }

    // ── TX thread ─────────────────────────────────────────────────────────────
    // Wakes on new cmd_vel or every 50ms (watchdog keepalive).
    void txThreadFunc()
    {
        while (running_) {
            double linear, angular;
            bool   watchdog_stop = false;

            {
                std::unique_lock<std::mutex> lock(cmd_mutex_);
                cmd_cv_.wait_for(lock, std::chrono::milliseconds(50));

                if (!running_) break;

                linear  = cmd_linear_;
                angular = cmd_angular_;
                cmd_updated_ = false;

                // Watchdog: if no cmd received recently, send zero
                if (cmd_vel_timeout_ > 0.0) {
                    double elapsed = (ros::Time::now() - last_cmd_time_).toSec();
                    if (elapsed > cmd_vel_timeout_) {
                        linear = angular = 0.0;
                        watchdog_stop = true;
                    }
                }
            }

            sendRpms(linear, angular);

            if (watchdog_stop) {
                ROS_WARN_THROTTLE(5.0, "cmd_vel watchdog: stopping motors");
            }
        }
    }

    // ── Send RPMs to all 4 motors ─────────────────────────────────────────────
    // Pure differential drive kinematics with velocity ramping.
    void sendRpms(double linear, double angular)
    {
        const double conv      = 60.0 / (2.0 * M_PI * wheel_radius_);
        const double left_vel  = linear - angular * wheel_track_ / 2.0;
        const double right_vel = linear + angular * wheel_track_ / 2.0;

        // ── Compute target RPM per motor ──────────────────────────────────────
        std::array<double, 4> target{};
        for (size_t i = 0; i < wheel_ids_.size(); i++) {
            double vel = (i == 1 || i == 3) ? right_vel : left_vel;
            if (wheel_directions_[i] == "backward") vel = -vel;
            target[i] = vel * conv;
        }

        // ── Ramp current_cmd_rpms_ toward target ──────────────────────────────
        auto now = std::chrono::steady_clock::now();
        double dt = std::chrono::duration<double>(now - last_tx_time_).count();
        last_tx_time_ = now;
        dt = std::min(dt, 0.2);  // cap to avoid big jumps after a pause

        const double max_step = accel_rpm_per_sec_ * dt;

        for (size_t i = 0; i < 4; i++) {
            double diff = target[i] - current_cmd_rpms_[i];
            if (std::abs(diff) <= max_step)
                current_cmd_rpms_[i] = target[i];
            else
                current_cmd_rpms_[i] += (diff > 0.0) ? max_step : -max_step;
        }

        // ── Send to motors ────────────────────────────────────────────────────
        std::lock_guard<std::mutex> bus_lock(bus_mutex_);
        for (size_t i = 0; i < wheel_ids_.size(); i++) {
            auto rpm_val = static_cast<int16_t>(std::round(current_cmd_rpms_[i]));
            auto frame   = ddsm115::buildRpmFrame(
                               static_cast<uint8_t>(wheel_ids_[i]), rpm_val);
            serial_.flushInput();
            serial_.write(frame.data(), frame.size());
            std::this_thread::sleep_for(std::chrono::milliseconds(inter_cmd_gap_ms_));
        }
        serial_.flushInput();
    }

    // ── Feedback thread ───────────────────────────────────────────────────────
    void feedbackThreadFunc()
    {
        const auto period = std::chrono::duration<double>(1.0 / feedback_rate_hz_);
        auto next_wake    = std::chrono::steady_clock::now() + period;

        while (running_) {
            {
                std::lock_guard<std::mutex> bus_lock(bus_mutex_);
                for (size_t i = 0; i < wheel_ids_.size(); i++) {
                    pollFeedback(static_cast<uint8_t>(wheel_ids_[i]),
                                 static_cast<int>(i));
                }
            }
            publishOdometry();
            publishMotorFeedback();

            std::this_thread::sleep_until(next_wake);
            next_wake += period;
        }
    }

    // ── Poll one motor for feedback ───────────────────────────────────────────
    void pollFeedback(uint8_t motor_id, int idx)
    {
        auto req = ddsm115::buildFeedbackRequestFrame(motor_id);
        serial_.flushInput();
        serial_.write(req.data(), req.size());

        // Read reply: scan for a valid 10-byte frame starting with motor_id
        ddsm115::Frame reply{};
        size_t filled = 0;
        auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::milliseconds(50);

        while (filled < ddsm115::FRAME_SIZE &&
               std::chrono::steady_clock::now() < deadline)
        {
            uint8_t byte;
            size_t  n = serial_.read(&byte, 1);
            if (n == 0) continue;

            if (filled == 0 && byte != motor_id) continue;  // wait for ID
            reply[filled++] = byte;
        }

        if (filled < ddsm115::FRAME_SIZE) {
            ROS_WARN_THROTTLE(2.0, "Motor %d: feedback timeout", motor_id);
            return;
        }

        auto fb = ddsm115::parseFeedback(reply, motor_id);
        if (!fb.valid) {
            ROS_WARN_THROTTLE(2.0, "Motor %d: invalid feedback (CRC or mode mismatch)",
                              motor_id);
            return;
        }

        if (fb.error) {
            ROS_WARN_THROTTLE(1.0,
                "Motor %d error flags: 0x%02X "
                "(sensor=%d overcurrent=%d phase=%d stall=%d)",
                motor_id, fb.error,
                fb.error & 0x01, (fb.error >> 1) & 0x01,
                (fb.error >> 2) & 0x01, (fb.error >> 3) & 0x01);
        }

        // Apply direction convention
        int16_t rpm = fb.rpm;
        if (wheel_directions_[static_cast<size_t>(idx)] == "backward") rpm = -rpm;

        {
            std::lock_guard<std::mutex> lock(feedback_mutex_);
            motor_rpms_[idx]     = rpm;
            motor_currents_[idx] = fb.current;
        }
    }

    // ── Publish odometry ─────────────────────────────────────────────────────
    void publishOdometry()
    {
        std::array<int16_t, 4> rpms;
        {
            std::lock_guard<std::mutex> lock(feedback_mutex_);
            rpms = motor_rpms_;
        }

        ros::Time now = ros::Time::now();
        double dt = (now - last_odom_time_).toSec();
        last_odom_time_ = now;

        if (dt <= 0.0 || dt > 1.0) return;

        const double conv  = (2.0 * M_PI * wheel_radius_) / 60.0;
        double v_left  = (rpms[0] + rpms[2]) / 2.0 * conv;
        double v_right = (rpms[1] + rpms[3]) / 2.0 * conv;

        double linear  = (v_left + v_right) / 2.0;
        double angular = (v_right - v_left) / wheel_track_;

        x_     += linear * std::cos(theta_) * dt;
        y_     += linear * std::sin(theta_) * dt;
        theta_ += angular * dt;

        geometry_msgs::Quaternion q =
            tf::createQuaternionMsgFromYaw(theta_);

        // TF
        geometry_msgs::TransformStamped tf_msg;
        tf_msg.header.stamp    = now;
        tf_msg.header.frame_id = "odom";
        tf_msg.child_frame_id  = "base_link";
        tf_msg.transform.translation.x = x_;
        tf_msg.transform.translation.y = y_;
        tf_msg.transform.translation.z = 0.0;
        tf_msg.transform.rotation = q;
        tf_broadcaster_.sendTransform(tf_msg);

        // Odometry message
        nav_msgs::Odometry odom;
        odom.header.stamp    = now;
        odom.header.frame_id = "odom";
        odom.child_frame_id  = "base_link";

        odom.pose.pose.position.x  = x_;
        odom.pose.pose.position.y  = y_;
        odom.pose.pose.orientation = q;

        odom.twist.twist.linear.x  = linear;
        odom.twist.twist.angular.z = angular;

        // Covariance
        odom.pose.covariance  = {0.01, 0, 0, 0, 0, 0,
                                  0, 0.01, 0, 0, 0, 0,
                                  0, 0, 999, 0, 0, 0,
                                  0, 0, 0, 999, 0, 0,
                                  0, 0, 0, 0, 999, 0,
                                  0, 0, 0, 0, 0, 0.05};
        odom.twist.covariance = odom.pose.covariance;

        odom_pub_.publish(odom);
    }

    // ── Publish motor RPMs and currents ────────────────────────────────────────
    void publishMotorFeedback()
    {
        std::lock_guard<std::mutex> lock(feedback_mutex_);

        std_msgs::Float32MultiArray rpm_msg, cur_msg;
        for (size_t i = 0; i < 4; i++) {
            rpm_msg.data.push_back(static_cast<float>(motor_rpms_[i]));
            cur_msg.data.push_back(motor_currents_[i]);
        }
        rpm_pub_.publish(rpm_msg);
        current_pub_.publish(cur_msg);
    }

    // ── Members ───────────────────────────────────────────────────────────────
    ros::NodeHandle nh_, pnh_;
    ros::Subscriber cmd_vel_sub_;
    ros::Publisher  odom_pub_, rpm_pub_, current_pub_;
    tf::TransformBroadcaster tf_broadcaster_;

    serial::Serial serial_;

    // Parameters
    std::vector<int>         wheel_ids_;
    std::vector<std::string> wheel_directions_;
    double wheel_radius_, wheel_track_, wheel_base_;
    double feedback_rate_hz_, cmd_vel_timeout_;
    int    inter_cmd_gap_ms_;
    double accel_rpm_per_sec_;

    // Velocity ramp state (TX thread only — no mutex needed)
    std::array<double, 4>                        current_cmd_rpms_{};
    std::chrono::steady_clock::time_point        last_tx_time_{};

    // Command state
    std::mutex              cmd_mutex_;
    std::condition_variable cmd_cv_;
    double   cmd_linear_   = 0.0;
    double   cmd_angular_  = 0.0;
    bool     cmd_updated_  = false;
    ros::Time last_cmd_time_;

    // Feedback state
    std::mutex              feedback_mutex_;
    std::array<int16_t, 4>  motor_rpms_;
    std::array<float, 4>    motor_currents_;

    // Odometry state
    double    x_ = 0, y_ = 0, theta_ = 0;
    ros::Time last_odom_time_;

    // Threads
    std::atomic<bool>  running_;
    std::thread        tx_thread_;
    std::thread        feedback_thread_;
    std::mutex         bus_mutex_;
};

int main(int argc, char** argv)
{
    ros::init(argc, argv, "base_controller");
    BaseControllerNode node;
    node.spin();
    return 0;
}
