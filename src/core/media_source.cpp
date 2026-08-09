#include "core/media_source.hpp"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <iomanip>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>

namespace ffgui {

double RationalFrameRate::value() const noexcept {
    return denominator > 0 ? static_cast<double>(numerator) / denominator : 0.0;
}

TimeNs RationalFrameRate::frame_duration() const {
    if (numerator <= 0 || denominator <= 0) {
        throw std::invalid_argument("frame rate must be positive");
    }
    return static_cast<TimeNs>(std::llround(
        static_cast<long double>(kNanosecondsPerSecond) * denominator / numerator));
}

std::size_t ImageSequenceDescriptor::frame_count() const noexcept {
    return last_frame >= first_frame
        ? static_cast<std::size_t>(static_cast<long long>(last_frame) - first_frame + 1)
        : 0;
}

bool ImageSequenceDescriptor::has_frame(int frame) const noexcept {
    return std::binary_search(present_frames.begin(), present_frames.end(), frame);
}

int ImageSequenceDescriptor::nearest_present_frame(int frame) const {
    if (present_frames.empty()) throw std::runtime_error("image sequence has no frames");
    const auto next = std::lower_bound(present_frames.begin(), present_frames.end(), frame);
    if (next == present_frames.begin()) return *next;
    if (next == present_frames.end()) return present_frames.back();
    const auto previous = *std::prev(next);
    return frame - previous <= *next - frame ? previous : *next;
}

std::filesystem::path ImageSequenceDescriptor::frame_path(int frame) const {
    std::ostringstream name;
    name << prefix;
    if (frame < 0) {
        name << '-';
        frame = -frame;
    }
    name << std::setw(padding) << std::setfill('0') << frame << suffix;
    return directory / std::filesystem::path(name.str());
}

namespace {

std::string lower_extension(const std::filesystem::path& path) {
    auto extension = path.extension().string();
    std::ranges::transform(extension, extension.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    return extension;
}

std::string regex_escape(std::string_view value) {
    static constexpr std::string_view special = R"(.^$|()[]{}*+?\)";
    std::string escaped;
    escaped.reserve(value.size() * 2);
    for (const char character : value) {
        if (special.find(character) != std::string_view::npos) escaped.push_back('\\');
        escaped.push_back(character);
    }
    return escaped;
}

}  // namespace

bool is_supported_still_extension(const std::filesystem::path& path) {
    static const std::set<std::string> extensions{
        ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".bmp", ".webp",
        ".dpx", ".hdr", ".exr"};
    return extensions.contains(lower_extension(path));
}

bool is_exr_extension(const std::filesystem::path& path) {
    return lower_extension(path) == ".exr";
}

std::optional<ImageSequenceDescriptor> detect_image_sequence(
    const std::filesystem::path& selected,
    RationalFrameRate default_frame_rate) {
    if (!is_supported_still_extension(selected) || !std::filesystem::is_regular_file(selected)) {
        return std::nullopt;
    }
    const auto filename = selected.filename().string();
    static const std::regex numbered(R"(^(.*?)(-?)(\d+)(\.[^.]+)$)");
    std::smatch selectedMatch;
    if (!std::regex_match(filename, selectedMatch, numbered)) return std::nullopt;

    const auto prefix = selectedMatch[1].str();
    const auto padding = static_cast<int>(selectedMatch[3].str().size());
    const auto suffix = selectedMatch[4].str();
    const std::regex sibling(
        "^" + regex_escape(prefix) + "(-?)([0-9]{" + std::to_string(padding) + "})" +
        regex_escape(suffix) + "$", std::regex::icase);
    std::vector<int> frames;
    for (const auto& entry : std::filesystem::directory_iterator(selected.parent_path())) {
        if (!entry.is_regular_file()) continue;
        std::smatch match;
        const auto candidate = entry.path().filename().string();
        if (!std::regex_match(candidate, match, sibling)) continue;
        auto number = std::stoi(match[2].str());
        if (match[1].str() == "-") number = -number;
        frames.push_back(number);
    }
    std::sort(frames.begin(), frames.end());
    frames.erase(std::unique(frames.begin(), frames.end()), frames.end());
    if (frames.size() < 2) return std::nullopt;

    ImageSequenceDescriptor result;
    result.directory = std::filesystem::absolute(selected.parent_path());
    result.prefix = prefix;
    result.suffix = suffix;
    result.padding = padding;
    result.first_frame = frames.front();
    result.last_frame = frames.back();
    result.frame_rate = default_frame_rate;
    result.present_frames = std::move(frames);
    for (int frame = result.first_frame; frame <= result.last_frame; ++frame) {
        if (!result.has_frame(frame)) result.missing_frames.push_back(frame);
        if (frame == result.last_frame) break;
    }
    return result;
}

}  // namespace ffgui
