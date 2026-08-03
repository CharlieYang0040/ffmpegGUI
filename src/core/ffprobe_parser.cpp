#include "core/ffprobe_parser.hpp"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <limits>
#include <stdexcept>
#include <string>

namespace ffgui {
namespace {

std::string_view trim(std::string_view value) {
    while (!value.empty() && (std::isspace(static_cast<unsigned char>(value.front())) ||
                              value.front() == ',' || value.front() == '"')) {
        value.remove_prefix(1);
    }
    while (!value.empty() && (std::isspace(static_cast<unsigned char>(value.back())) ||
                              value.back() == ',' || value.back() == '"')) {
        value.remove_suffix(1);
    }
    return value;
}

}  // namespace

TimeNs parse_ffprobe_seconds(std::string_view value) {
    value = trim(value);
    if (value.empty() || value == "N/A") {
        throw std::invalid_argument("FFprobe timestamp is unavailable");
    }
    bool negative = false;
    if (value.front() == '-' || value.front() == '+') {
        negative = value.front() == '-';
        value.remove_prefix(1);
    }
    const auto decimal = value.find('.');
    const auto wholeText = value.substr(0, decimal);
    if (wholeText.empty()) {
        throw std::invalid_argument("FFprobe timestamp has no whole seconds");
    }
    TimeNs whole = 0;
    const auto [wholeEnd, wholeError] = std::from_chars(
        wholeText.data(), wholeText.data() + wholeText.size(), whole);
    if (wholeError != std::errc{} || wholeEnd != wholeText.data() + wholeText.size() ||
        whole > std::numeric_limits<TimeNs>::max() / kNanosecondsPerSecond) {
        throw std::out_of_range("FFprobe timestamp is outside nanosecond range");
    }

    TimeNs fraction = 0;
    if (decimal != std::string_view::npos) {
        auto fractionText = value.substr(decimal + 1);
        if (fractionText.empty()) {
            throw std::invalid_argument("FFprobe timestamp has an empty fraction");
        }
        const auto usedDigits = std::min<std::size_t>(9, fractionText.size());
        for (std::size_t index = 0; index < usedDigits; ++index) {
            const char digit = fractionText[index];
            if (digit < '0' || digit > '9') {
                throw std::invalid_argument("FFprobe timestamp fraction is invalid");
            }
            fraction = fraction * 10 + (digit - '0');
        }
        for (std::size_t index = usedDigits; index < 9; ++index) {
            fraction *= 10;
        }
        for (std::size_t index = usedDigits; index < fractionText.size(); ++index) {
            if (fractionText[index] < '0' || fractionText[index] > '9') {
                throw std::invalid_argument("FFprobe timestamp fraction is invalid");
            }
        }
    }
    const auto magnitude = checked_add(whole * kNanosecondsPerSecond, fraction);
    return negative ? -magnitude : magnitude;
}

std::vector<TimeNs> parse_ffprobe_frame_pts(std::string_view output) {
    std::vector<TimeNs> result;
    std::size_t cursor = 0;
    while (cursor <= output.size()) {
        const auto end = output.find_first_of("\r\n", cursor);
        const auto line = trim(output.substr(cursor, end == std::string_view::npos
            ? output.size() - cursor
            : end - cursor));
        if (!line.empty() && line != "N/A") {
            result.push_back(parse_ffprobe_seconds(line));
        }
        if (end == std::string_view::npos) {
            break;
        }
        cursor = end + 1;
        if (output[end] == '\r' && cursor < output.size() && output[cursor] == '\n') {
            ++cursor;
        }
    }
    if (result.empty()) {
        return result;
    }
    std::sort(result.begin(), result.end());
    result.erase(std::unique(result.begin(), result.end()), result.end());
    const auto origin = result.front();
    for (auto& timestamp : result) {
        timestamp -= origin;
    }
    return result;
}

TimeNs estimated_media_end(const std::vector<TimeNs>& frame_pts) {
    if (frame_pts.empty()) {
        return 0;
    }
    const auto tailDuration = frame_pts.size() > 1
        ? std::max<TimeNs>(1, frame_pts.back() - frame_pts[frame_pts.size() - 2])
        : 1;
    return checked_add(frame_pts.back(), tailDuration);
}

}  // namespace ffgui
