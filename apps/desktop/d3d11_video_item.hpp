#pragma once

#include "integration/ges/ges_sequence_player.hpp"

#include <QQuickItem>
#include <QPointF>
#include <QtQml/qqmlregistration.h>

#include <atomic>
#include <mutex>

struct ID3D11Device;
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
    void submitFrame(ffgui::PreviewVideoFrame frame);
    [[nodiscard]] QPointF videoUvFromItem(qreal x, qreal y) const;

signals:
    void gpuReadyChanged();
    void d3d11DeviceReady(quintptr device);
    void framePresented(quint64 serial);
    void deviceLostChanged();
    void gpuDeviceRemoved();

protected:
    QSGNode* updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) override;
    void releaseResources() override;

private:
    void initializeGraphics();
    void invalidateGraphics();
    [[nodiscard]] bool noteDeviceRemoved(long status);

    mutable std::mutex frame_mutex_;
    ffgui::PreviewVideoFrame pending_frame_;
    ffgui::PreviewVideoFrame render_frame_;
    std::uint64_t rendered_serial_{};
    std::uint32_t layout_width_{};
    std::uint32_t layout_height_{};
    mutable std::mutex device_mutex_;
    ID3D11Device* device_{};
    ID3D11Texture2D* display_texture_{};
    std::atomic_bool device_lost_{};
};
