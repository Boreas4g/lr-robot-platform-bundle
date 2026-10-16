#include "robot_4wd_dds115_base_controller/ddsm115_protocol.hpp"

namespace ddsm115 {

uint8_t crc8(const uint8_t* data, size_t len)
{
    uint8_t crc = 0x00;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int j = 0; j < 8; j++) {
            crc = (crc & 0x01) ? (crc >> 1) ^ 0x8C : (crc >> 1);
        }
    }
    return crc;
}

float rawCurrentToAmps(int16_t raw)
{
    // Motor reports current as int16 mapped ±32767 → ±8 A
    return static_cast<float>(raw) * 8.0f / 32767.0f;
}

Frame buildRpmFrame(uint8_t id, int16_t rpm)
{
    Frame f{};
    f[0] = id;
    f[1] = CMD_VELOCITY;
    f[2] = static_cast<uint8_t>((rpm >> 8) & 0xFF);  // high byte
    f[3] = static_cast<uint8_t>(rpm & 0xFF);          // low byte
    // bytes 4-8 are zero
    f[9] = crc8(f.data(), 9);
    return f;
}

Frame buildFeedbackRequestFrame(uint8_t id)
{
    Frame f{};
    f[0] = id;
    f[1] = CMD_FEEDBACK;
    // bytes 2-8 are zero
    f[9] = crc8(f.data(), 9);
    return f;
}

Frame buildDriveModeFrame(uint8_t id, DriveMode mode)
{
    Frame f{};
    f[0] = id;
    f[1] = CMD_DRIVE_MODE;
    // bytes 2-7 are zero
    f[8] = static_cast<uint8_t>(mode);
    f[9] = crc8(f.data(), 9);
    return f;
}

Frame buildBrakeFrame(uint8_t id)
{
    Frame f{};
    f[0] = id;
    f[1] = CMD_VELOCITY;
    // bytes 2-6 are zero
    f[7] = 0xFF;  // brake flag
    // byte 8 is zero
    f[9] = crc8(f.data(), 9);
    return f;
}

MotorFeedback parseFeedback(const Frame& f, uint8_t expected_id)
{
    MotorFeedback fb;

    // Validate ID, mode and CRC
    if (f[0] != expected_id)         return fb;
    if (f[1] != REPLY_VELOCITY_MODE) return fb;

    uint8_t computed = crc8(f.data(), 9);
    if (f[9] != computed)            return fb;

    int16_t raw_cur = static_cast<int16_t>((f[2] << 8) | f[3]);
    int16_t raw_rpm = static_cast<int16_t>((f[4] << 8) | f[5]);

    fb.current = rawCurrentToAmps(raw_cur);
    fb.rpm     = raw_rpm;
    fb.error   = f[8];
    fb.valid   = true;
    return fb;
}

} // namespace ddsm115
