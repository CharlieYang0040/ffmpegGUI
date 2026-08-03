#include "core/subtitle_srt.hpp"

#include <algorithm>
#include <charconv>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace ffgui {
namespace {

std::string_view trim(std::string_view value) {
    while (!value.empty() && (value.front() == ' ' || value.front() == '\t')) value.remove_prefix(1);
    while (!value.empty() && (value.back() == ' ' || value.back() == '\t')) value.remove_suffix(1);
    return value;
}

int number(std::string_view value, const char* field) {
    value = trim(value);
    int result = 0;
    const auto parsed = std::from_chars(value.data(), value.data() + value.size(), result);
    if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size()) {
        throw std::invalid_argument(std::string("invalid SRT ") + field);
    }
    return result;
}

TimeNs timestamp(std::string_view value) {
    value = trim(value);
    const auto firstColon = value.find(':');
    const auto secondColon = value.find(':', firstColon == value.npos ? 0 : firstColon + 1);
    const auto fraction = value.find_first_of(",.", secondColon == value.npos ? 0 : secondColon + 1);
    if (firstColon == value.npos || secondColon == value.npos || fraction == value.npos) {
        throw std::invalid_argument("invalid SRT timestamp");
    }
    const auto hours = number(value.substr(0, firstColon), "hours");
    const auto minutes = number(value.substr(firstColon + 1, secondColon - firstColon - 1), "minutes");
    const auto seconds = number(value.substr(secondColon + 1, fraction - secondColon - 1), "seconds");
    auto fractionText = value.substr(fraction + 1);
    if (fractionText.empty() || fractionText.size() > 3 || minutes > 59 || seconds > 59 ||
        hours < 0 || hours > 9999 || minutes < 0 || seconds < 0) {
        throw std::invalid_argument("invalid SRT timestamp range");
    }
    auto milliseconds = number(fractionText, "milliseconds");
    if (fractionText.size() == 1) milliseconds *= 100;
    else if (fractionText.size() == 2) milliseconds *= 10;
    const auto totalSeconds = checked_add(
        static_cast<TimeNs>(hours) * 3600,
        checked_add(static_cast<TimeNs>(minutes) * 60, seconds));
    return checked_add(totalSeconds * kNanosecondsPerSecond,
                       static_cast<TimeNs>(milliseconds) * 1'000'000);
}

std::string format_timestamp(TimeNs value) {
    const auto milliseconds = value / 1'000'000;
    std::ostringstream stream;
    stream << std::setw(2) << std::setfill('0') << milliseconds / 3'600'000 << ':'
           << std::setw(2) << (milliseconds / 60'000) % 60 << ':'
           << std::setw(2) << (milliseconds / 1'000) % 60 << ','
           << std::setw(3) << milliseconds % 1'000;
    return stream.str();
}

std::string format_text(std::string_view text) {
    std::string normalized;
    for (const auto character : text) {
        if (character == '\r') continue;
        if (character == '\n') normalized += "\r\n";
        else normalized += character;
    }
    return normalized;
}

}  // namespace

std::vector<SrtCue> parse_srt(std::string_view contents) {
    if (contents.starts_with("\xEF\xBB\xBF")) contents.remove_prefix(3);
    std::vector<std::string> lines;
    std::string current;
    for (const auto character : contents) {
        if (character == '\r') continue;
        if (character == '\n') {
            lines.push_back(std::move(current));
            current.clear();
        } else {
            current += character;
        }
    }
    lines.push_back(std::move(current));

    std::vector<SrtCue> cues;
    std::size_t cursor = 0;
    while (cursor < lines.size()) {
        while (cursor < lines.size() && trim(lines[cursor]).empty()) ++cursor;
        if (cursor >= lines.size()) break;
        if (lines[cursor].find("-->") == std::string::npos) ++cursor;
        if (cursor >= lines.size()) throw std::invalid_argument("SRT cue has no timestamp line");
        const auto arrow = lines[cursor].find("-->");
        if (arrow == std::string::npos) throw std::invalid_argument("SRT cue has no timestamp line");
        const auto start = timestamp(std::string_view(lines[cursor]).substr(0, arrow));
        const auto end = timestamp(std::string_view(lines[cursor]).substr(arrow + 3));
        if (end <= start) throw std::invalid_argument("SRT cue duration must be positive");
        ++cursor;
        std::string text;
        while (cursor < lines.size() && !trim(lines[cursor]).empty()) {
            if (!text.empty()) text += '\n';
            text += lines[cursor++];
        }
        if (trim(text).empty()) throw std::invalid_argument("SRT cue text must not be empty");
        cues.push_back(SrtCue{std::move(text), start, end - start});
    }
    return cues;
}

std::string serialize_srt(const std::vector<SrtCue>& cues) {
    std::vector<SrtCue> sorted = cues;
    std::ranges::sort(sorted, {}, &SrtCue::timeline_in);
    std::string result;
    for (std::size_t index = 0; index < sorted.size(); ++index) {
        const auto& cue = sorted[index];
        if (cue.text.empty() || cue.timeline_in < 0 || cue.duration <= 0) {
            throw std::invalid_argument("cannot serialize an invalid SRT cue");
        }
        result += std::to_string(index + 1) + "\r\n";
        result += format_timestamp(cue.timeline_in) + " --> " +
                  format_timestamp(checked_add(cue.timeline_in, cue.duration)) + "\r\n";
        result += format_text(cue.text) + "\r\n\r\n";
    }
    return result;
}

}  // namespace ffgui
