#pragma once

#include "integration/ges/ges_sequence_player.hpp"

#include <QQuickItem>
#include <QtQml/qqmlregistration.h>

#include <mutex>

struct ID3D11Device;
struct ID3D11Texture2D;

class VideoPreviewItem : public QQuickItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(bool gpuReady READ gpuReady NOTIFY gpuReadyChanged)

public:
    explicit VideoPreviewItem(QQuickItem* parent = nullptr);
    ~VideoPreviewItem() override;

    [[nodiscard]] bool gpuReady() const noexcept;
    [[nodiscard]] quintptr devicePointer() const noexcept;
    void submitFrame(ffgui::PreviewVideoFrame frame);

signals:
    void gpuReadyChanged();
    void d3d11DeviceReady(quintptr device);
    void framePresented(quint64 serial);

protected:
    QSGNode* updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) override;
    void releaseResources() override;

private:
    void initializeGraphics();
    void invalidateGraphics();

    mutable std::mutex frame_mutex_;
    ffgui::PreviewVideoFrame pending_frame_;
    ffgui::PreviewVideoFrame render_frame_;
    std::uint64_t rendered_serial_{};
    mutable std::mutex device_mutex_;
    ID3D11Device* device_{};
    ID3D11Texture2D* display_texture_{};
};
