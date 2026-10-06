#pragma once

#include <cstdint>
#include <cstring>

// Standalone IEEE-754 binary16 <-> float bit conversion helpers. Kept free of
// any AscendC / kernel_operator.h / simt_api dependency so that both SIMD
// (kernel_operator.h) and SIMT (simt_api/asc_simt.h) translation units can
// include it (the two device headers are mutually exclusive).

namespace lab {

inline uint16_t F16(float value)
{
    uint32_t bits;
    std::memcpy(&bits, &value, sizeof(bits));
    const uint16_t sign = static_cast<uint16_t>((bits >> 16) & 0x8000u);
    int32_t exponent = static_cast<int32_t>((bits >> 23) & 0xffu) - 127 + 15;
    uint32_t mantissa = bits & 0x7fffffu;

    if (exponent <= 0) {
        if (exponent < -10) {
            return sign;
        }
        mantissa = (mantissa | 0x800000u) >> (1 - exponent);
        return static_cast<uint16_t>(sign | ((mantissa + 0x1000u) >> 13));
    }
    if (exponent >= 31) {
        return static_cast<uint16_t>(sign | 0x7c00u | (mantissa != 0 ? 0x0200u : 0));
    }
    return static_cast<uint16_t>(sign | (static_cast<uint32_t>(exponent) << 10) |
                                 ((mantissa + 0x1000u) >> 13));
}

inline float F32(uint16_t value)
{
    const uint32_t sign = static_cast<uint32_t>(value & 0x8000u) << 16;
    uint32_t exponent = (value >> 10) & 0x1fu;
    uint32_t mantissa = value & 0x03ffu;
    uint32_t bits;

    if (exponent == 0) {
        if (mantissa == 0) {
            bits = sign;
        } else {
            int32_t adjustedExponent = 127 - 15 + 1;
            while ((mantissa & 0x0400u) == 0) {
                mantissa <<= 1;
                --adjustedExponent;
            }
            bits = sign | (static_cast<uint32_t>(adjustedExponent) << 23) | ((mantissa & 0x03ffu) << 13);
        }
    } else if (exponent == 31) {
        bits = sign | 0x7f800000u | (mantissa << 13);
    } else {
        bits = sign | ((exponent + 127 - 15) << 23) | (mantissa << 13);
    }

    float converted;
    std::memcpy(&converted, &bits, sizeof(converted));
    return converted;
}

}  // namespace lab
