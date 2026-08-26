#pragma once

#include "integration/ges/ges_sequence_player.hpp"

#include <QQuickItem>
#include <QPointF>
#include <QtQml/qqmlregistration.h>

#include <atomic>
#include <array>
#include <mutex>

struct ID3D11Device;
struct ID3D11DeviceContext4;
struct ID3D11Fence;
struct ID3D11Texture2D;

class VideoPreviewItem : public QQuickItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(bool gpuReady READ gpuReady NOTIFY gpuReadyChanged)
    Q_PROPERTY(bool deviceLost READ deviceLost NOTIFY deviceLostChanged)

public:
    explicit VideoPreviewItem(QQuickItem* parent = nullptr);
    ~VideoPreviewItem() override;

    [[nodiscard]] bool gpuReady() const noexcept;
    [[nodiscard]] bool deviceLost() const noexcept {
        return device_lost_.load(std::memory_order_acquire);
    }
    [[nodiscard]] quintptr devicePointer() const noexcept;
    [[nodiscard]] long deviceRemovedReason() const noexcept;
    void submitFrame(ffgui::PreviewVideoFrame frame);
    [[nodiscard]] QPointF videoUvFromItem(qreal x, qreal y) const;
    Q_INVOKABLE void retireGpuResources(bool markDeviceLost = false);

signals:
    void gpuReadyChanged();
    void d3d11DeviceReady(quintptr device);
    void framePresented(quint64 serial);
    void deviceLostChanged();
    void gpuDeviceRemoved();
    void gpuResourcesRetired(bool deviceLost);

protected:
    QSGNode* updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) override;
    void releaseResources() override;

private:
    void initializeGraphics();
    void invalidateGraphics();
    [[nodiscard]] bool waitForPooledFrame(
        ffgui::PreviewVideoFrame& frame, ID3D11Texture2D** texture);
    void releasePooledFrame(ffgui::PreviewVideoFrame& frame) noexcept;
    void clearPooledResources() noexcept;
    [[nodiscard]] bool noteDeviceRemoved(long status);

    mutable std::mutex frame_mutex_;
    ffgui::PreviewVideoFrame pending_frame_;
    ffgui::PreviewVideoFrame render_frame_;
    std::uint64_t rendered_serial_{};
    std::uint64_t rendered_pipeline_generation_{};
    std::uint64_t rendered_device_epoch_{};
    std::uint32_t layout_width_{};
    std::uint32_t layout_height_{};
    mutable std::mutex device_mutex_;
    ID3D11Device* device_{};
    ID3D11DeviceContext4* device_context4_{};
    ID3D11Texture2D* display_texture_{};
    struct PooledResources final {
        std::uintptr_t texture_handle{};
        std::uintptr_t ready_fence_handle{};
        std::uintptr_t release_fence_handle{};
        ID3D11Texture2D* texture{};
        ID3D11Fence* ready_fence{};
        ID3D11Fence* release_fence{};
    };
    std::array<PooledResources, 4> pooled_resources_{};
    std::atomic_bool device_lost_{};
    std::atomic_bool retirement_requested_{};
    std::atomic_bool retirement_marks_device_lost_{};
    std::atomic_bool resources_retired_{};
};
