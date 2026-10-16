#pragma once
#include <array>
#include <cstdint>

namespace ddsm115 {

static constexpr int    FRAME_SIZE          = 10;
static constexpr uint8_t CMD_VELOCITY       = 0x64;
static constexpr uint8_t CMD_FEEDBACK       = 0x74;
static constexpr uint8_t CMD_DRIVE_MODE     = 0xA0;
static constexpr uint8_t REPLY_VELOCITY_MODE = 0x02;

enum class DriveMode : uint8_t {
    CURRENT  = 0x01,
    VELOCITY = 0x02,
    POSITION = 0x03
};

struct MotorFeedback {
    int16_t rpm     = 0;
    float   current = 0.0f;   // Amperes
    uint8_t error   = 0;
    bool    valid   = false;
};

using Frame = std::array<uint8_t, FRAME_SIZE>;

// CRC-8/MAXIM (polynomial 0x8C reflected)
uint8_t crc8(const uint8_t* data, size_t len);

Frame buildRpmFrame(uint8_t id, int16_t rpm);
Frame buildFeedbackRequestFrame(uint8_t id);
Frame buildDriveModeFrame(uint8_t id, DriveMode mode);
Frame buildBrakeFrame(uint8_t id);

MotorFeedback parseFeedback(const Frame& frame, uint8_t expected_id);

float rawCurrentToAmps(int16_t raw);

} // namespace ddsm115
