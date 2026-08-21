#pragma once

#include <QString>

class QWindow;

enum class HdrWindowMode { sdr, scrgb, rec2020_pq };

struct HdrDisplayProbe final {
    bool hdr_capable{};
    int max_luminance_nits{400};
    int sdr_white_nits{203};
    QString monitor_icc_path;
    QString adapter_name;
};

[[nodiscard]] HdrDisplayProbe probe_hdr_display(QWindow* window);
[[nodiscard]] bool apply_window_color_space(
    QWindow* window, HdrWindowMode mode, const QString& monitor_icc_path);
[[nodiscard]] QString hdr_window_mode_name(HdrWindowMode mode);
