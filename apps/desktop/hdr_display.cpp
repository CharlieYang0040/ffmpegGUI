#include "hdr_display.hpp"

#include <QColorSpace>
#include <QFile>
#include <QWindow>

#ifdef Q_OS_WIN
#include <windows.h>
#include <dxgi1_6.h>
#include <algorithm>
#endif

QString hdr_window_mode_name(HdrWindowMode mode) {
    switch (mode) {
    case HdrWindowMode::scrgb: return QStringLiteral("scRGB");
    case HdrWindowMode::rec2020_pq: return QStringLiteral("Rec.2020 PQ");
    case HdrWindowMode::sdr: return QStringLiteral("SDR");
    }
    return QStringLiteral("SDR");
}

#ifdef Q_OS_WIN

namespace {

QString icc_path_for_monitor(HMONITOR monitor) {
    MONITORINFOEXW info{};
    info.cbSize = sizeof(info);
    if (monitor == nullptr || !GetMonitorInfoW(monitor, &info)) return {};
    HDC device = CreateDCW(L"DISPLAY", info.szDevice, nullptr, nullptr);
    if (device == nullptr) return {};
    DWORD size = 0;
    GetICMProfileW(device, &size, nullptr);
    QString path;
    if (size > 1) {
        std::wstring buffer(size, L'\0');
        if (GetICMProfileW(device, &size, buffer.data()) && !buffer.empty()) {
            path = QString::fromWCharArray(buffer.c_str());
        }
    }
    DeleteDC(device);
    return path;
}

}  // namespace

HdrDisplayProbe probe_hdr_display(QWindow* window) {
    HdrDisplayProbe probe;
    HMONITOR monitor = nullptr;
    if (window != nullptr) {
        const auto handle = reinterpret_cast<HWND>(window->winId());
        if (handle != nullptr) {
            monitor = MonitorFromWindow(handle, MONITOR_DEFAULTTONEAREST);
        }
    }
    if (monitor == nullptr) monitor = MonitorFromWindow(nullptr, MONITOR_DEFAULTTOPRIMARY);
    probe.monitor_icc_path = icc_path_for_monitor(monitor);

    IDXGIFactory1* factory = nullptr;
    if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&factory))) ||
        factory == nullptr) {
        return probe;
    }
    for (UINT adapterIndex = 0;; ++adapterIndex) {
        IDXGIAdapter1* adapter = nullptr;
        if (factory->EnumAdapters1(adapterIndex, &adapter) == DXGI_ERROR_NOT_FOUND) break;
        if (adapter == nullptr) continue;
        for (UINT outputIndex = 0;; ++outputIndex) {
            IDXGIOutput* output = nullptr;
            if (adapter->EnumOutputs(outputIndex, &output) == DXGI_ERROR_NOT_FOUND) break;
            if (output == nullptr) continue;
            DXGI_OUTPUT_DESC desc{};
            output->GetDesc(&desc);
            const bool sameMonitor = monitor == nullptr || desc.Monitor == monitor;
            IDXGIOutput6* output6 = nullptr;
            if (sameMonitor &&
                SUCCEEDED(output->QueryInterface(__uuidof(IDXGIOutput6),
                    reinterpret_cast<void**>(&output6))) &&
                output6 != nullptr) {
                DXGI_OUTPUT_DESC1 desc1{};
                if (SUCCEEDED(output6->GetDesc1(&desc1))) {
                    probe.hdr_capable =
                        desc1.ColorSpace == DXGI_COLOR_SPACE_RGB_FULL_G2084_NONE_P2020 ||
                        desc1.ColorSpace == DXGI_COLOR_SPACE_RGB_FULL_G10_NONE_P709 ||
                        (desc1.BitsPerColor >= 10 && desc1.MaxLuminance >= 400.0f);
                    probe.max_luminance_nits = std::max(
                        100, static_cast<int>(desc1.MaxLuminance + 0.5f));
                    if (desc1.MaxFullFrameLuminance >= 80.0f &&
                        desc1.MaxFullFrameLuminance <= 500.0f) {
                        probe.sdr_white_nits = static_cast<int>(desc1.MaxFullFrameLuminance + 0.5f);
                    }
                    DXGI_ADAPTER_DESC adapterDesc{};
                    if (SUCCEEDED(adapter->GetDesc(&adapterDesc))) {
                        probe.adapter_name = QString::fromWCharArray(adapterDesc.Description);
                    }
                }
                output6->Release();
            }
            output->Release();
            if (sameMonitor && probe.hdr_capable) {
                adapter->Release();
                factory->Release();
                return probe;
            }
        }
        adapter->Release();
    }
    factory->Release();
    return probe;
}

#else

HdrDisplayProbe probe_hdr_display(QWindow*) {
    return {};
}

#endif

bool apply_window_color_space(
    QWindow* window, HdrWindowMode mode, const QString& monitor_icc_path) {
    if (window == nullptr) return false;
    QColorSpace space;
    switch (mode) {
    case HdrWindowMode::scrgb:
        space = QColorSpace(QColorSpace::SRgbLinear);
        break;
    case HdrWindowMode::rec2020_pq:
        space = QColorSpace(
            QColorSpace::Primaries::Bt2020, QColorSpace::TransferFunction::St2084);
        break;
    case HdrWindowMode::sdr:
        if (!monitor_icc_path.isEmpty()) {
            QFile profile(monitor_icc_path);
            if (profile.open(QIODevice::ReadOnly)) {
                space = QColorSpace::fromIccProfile(profile.readAll());
            }
        }
        if (!space.isValid()) space = QColorSpace(QColorSpace::SRgb);
        break;
    }
    if (!space.isValid()) return false;
    window->setColorSpace(space);
    return window->colorSpace().isValid();
}
