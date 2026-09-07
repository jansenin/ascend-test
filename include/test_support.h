#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "acl/acl.h"
#include "device_kernels.h"

namespace lab {

inline void CheckAcl(aclError status, const char* operation)
{
    if (status != ACL_SUCCESS) {
        throw std::runtime_error(std::string(operation) + " failed with ACL error " + std::to_string(status));
    }
}

class Runtime {
public:
    Runtime()
    {
        CheckAcl(aclInit(nullptr), "aclInit");
        initialized_ = true;
        CheckAcl(aclrtSetDevice(0), "aclrtSetDevice");
        deviceSet_ = true;
        CheckAcl(aclrtCreateStream(&stream_), "aclrtCreateStream");
    }

    Runtime(const Runtime&) = delete;
    Runtime& operator=(const Runtime&) = delete;

    ~Runtime()
    {
        if (stream_ != nullptr) {
            aclrtDestroyStream(stream_);
        }
        if (deviceSet_) {
            aclrtResetDevice(0);
        }
        if (initialized_) {
            aclFinalize();
        }
    }

    aclrtStream stream() const { return stream_; }
    void Sync() const { CheckAcl(aclrtSynchronizeStream(stream_), "aclrtSynchronizeStream"); }

private:
    aclrtStream stream_ = nullptr;
    bool initialized_ = false;
    bool deviceSet_ = false;
};

class DeviceBuffer {
public:
    explicit DeviceBuffer(size_t bytes) : bytes_(bytes)
    {
        CheckAcl(aclrtMalloc(reinterpret_cast<void**>(&data_), bytes_, ACL_MEM_MALLOC_HUGE_FIRST), "aclrtMalloc");
    }

    DeviceBuffer(const DeviceBuffer&) = delete;
    DeviceBuffer& operator=(const DeviceBuffer&) = delete;

    ~DeviceBuffer()
    {
        if (data_ != nullptr) {
            aclrtFree(data_);
        }
    }

    uint8_t* data() const { return data_; }

    void CopyFrom(const void* source) const
    {
        CheckAcl(aclrtMemcpy(data_, bytes_, source, bytes_, ACL_MEMCPY_HOST_TO_DEVICE), "host-to-device copy");
    }

    void CopyTo(void* destination) const
    {
        CheckAcl(aclrtMemcpy(destination, bytes_, data_, bytes_, ACL_MEMCPY_DEVICE_TO_HOST), "device-to-host copy");
    }

private:
    uint8_t* data_ = nullptr;
    size_t bytes_ = 0;
};

inline aclFloat16 Half(float value)
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
        return static_cast<aclFloat16>(sign | ((mantissa + 0x1000u) >> 13));
    }
    if (exponent >= 31) {
        return static_cast<aclFloat16>(sign | 0x7c00u | (mantissa != 0 ? 0x0200u : 0));
    }
    return static_cast<aclFloat16>(sign | (static_cast<uint32_t>(exponent) << 10) |
                                   ((mantissa + 0x1000u) >> 13));
}

inline float Float(aclFloat16 value)
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

inline bool Verify(const std::vector<aclFloat16>& actual, const std::vector<float>& expected, float tolerance,
                   const char* testName)
{
    for (size_t i = 0; i < actual.size(); ++i) {
        const float value = Float(actual[i]);
        if (std::fabs(value - expected[i]) > tolerance) {
            std::cerr << testName << " mismatch at " << i << ": expected " << expected[i] << ", got " << value
                      << '\n';
            return false;
        }
    }
    std::cout << testName << ": PASS (" << actual.size() << " elements)\n";
    return true;
}

inline std::vector<aclFloat16> MakeInput(size_t count, int seed)
{
    std::vector<aclFloat16> values(count);
    for (size_t i = 0; i < count; ++i) {
        const int centered = static_cast<int>((i * 17 + static_cast<size_t>(seed) * 13) % 29) - 14;
        values[i] = Half(static_cast<float>(centered) / 16.0f);
    }
    return values;
}

inline std::vector<aclFloat16> MakeRectangularIdentity()
{
    std::vector<aclFloat16> values(kK * kN, Half(0.0f));
    for (uint32_t i = 0; i < kK; ++i) {
        values[i * kN + i] = Half(1.0f);
    }
    return values;
}

}  // namespace lab
