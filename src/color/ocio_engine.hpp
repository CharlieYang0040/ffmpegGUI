#pragma once

#include "core/color_pipeline.hpp"

#include <cstddef>
#include <memory>
#include <string>
#include <vector>

namespace ffgui {

class OcioEngine final {
public:
    explicit OcioEngine(const ColorPipelineSettings& settings);
    ~OcioEngine();
    OcioEngine(OcioEngine&&) noexcept;
    OcioEngine& operator=(OcioEngine&&) noexcept;
    OcioEngine(const OcioEngine&) = delete;
    OcioEngine& operator=(const OcioEngine&) = delete;

    [[nodiscard]] bool managed() const noexcept;
    [[nodiscard]] std::string config_name() const;
    [[nodiscard]] std::vector<std::string> color_spaces() const;
    void transform_rgba32f(float* pixels, std::size_t width, std::size_t height,
                           const std::string& input_space,
                           const std::string& output_space) const;
    [[nodiscard]] std::string bake_cube(const std::string& input_space,
                                        const std::string& output_space,
                                        int cube_size) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace ffgui
