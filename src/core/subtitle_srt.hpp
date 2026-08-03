#pragma once

#include "core/time.hpp"

#include <string>
#include <string_view>
#include <vector>

namespace ffgui {

struct SrtCue final {
    std::string text;
    TimeNs timeline_in{};
    TimeNs duration{};

    bool operator==(const SrtCue&) const = default;
};

[[nodiscard]] std::vector<SrtCue> parse_srt(std::string_view contents);
[[nodiscard]] std::string serialize_srt(const std::vector<SrtCue>& cues);

}  // namespace ffgui
