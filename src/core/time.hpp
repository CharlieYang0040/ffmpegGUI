#pragma once

#include <cstdint>
#include <limits>
#include <stdexcept>

namespace ffgui {

using TimeNs = std::int64_t;

inline constexpr TimeNs kNanosecondsPerSecond = 1'000'000'000;

[[nodiscard]] inline TimeNs checked_add(TimeNs left, TimeNs right) {
    if (right > 0 && left > std::numeric_limits<TimeNs>::max() - right) {
        throw std::overflow_error("timeline time overflow");
    }
    if (right < 0 && left < std::numeric_limits<TimeNs>::min() - right) {
        throw std::overflow_error("timeline time underflow");
    }
    return left + right;
}

}  // namespace ffgui
