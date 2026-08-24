#include "d3d11_video_item.hpp"

#include <QMetaObject>
#include <QImage>
#include <QDebug>
#include <QQuickWindow>
#include <QSGSimpleTextureNode>
#include <QSGTexture>
#include <QSGRendererInterface>
#include <QtQuick/qsgtexture_platform.h>

#include <d3d11.h>
#include <d3d11_4.h>
#include <dxgi.h>

#include <algorithm>
#include <utility>

VideoPreviewItem::VideoPreviewItem(QQuickItem* parent) : QQuickItem(parent) {
    setFlag(ItemHasContents, true);
    connect(this, &QQuickItem::windowChanged, this, [this](QQuickWindow* itemWindow) {
        if (itemWindow == nullptr) return;
        connect(
            itemWindow,
            &QQuickWindow::beforeSynchronizing,
            this,
            &VideoPreviewItem::initializeGraphics,
            Qt::DirectConnection);
        connect(
            itemWindow,
            &QQuickWindow::sceneGraphInvalidated,
            this,
            &VideoPreviewItem::invalidateGraphics,
            Qt::DirectConnection);
    });
}

VideoPreviewItem::~VideoPreviewItem() {
    invalidateGraphics();
}

bool VideoPreviewItem::gpuReady() const noexcept {
    std::scoped_lock lock(device_mutex_);
    return device_ != nullptr;
}

quintptr VideoPreviewItem::devicePointer() const noexcept {
    std::scoped_lock lock(device_mutex_);
    return reinterpret_cast<quintptr>(device_);
}

void VideoPreviewItem::submitFrame(ffgui::PreviewVideoFrame frame) {
    {
        std::scoped_lock lock(frame_mutex_);
        pending_frame_ = std::move(frame);
    }
    // Only dirty this item. window()->update() forces a full scene-graph sync and
    // makes the whole shell flash while the timeline or bin is being skimmed.
    update();
}

QPointF VideoPreviewItem::videoUvFromItem(qreal x, qreal y) const {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    {
        std::scoped_lock lock(frame_mutex_);
        width = layout_width_ != 0 ? layout_width_
            : (render_frame_.width != 0 ? render_frame_.width : pending_frame_.width);
        height = layout_height_ != 0 ? layout_height_
            : (render_frame_.height != 0 ? render_frame_.height : pending_frame_.height);
    }
    const auto bounds = boundingRect();
    if (width == 0 || height == 0 || bounds.width() <= 0 || bounds.height() <= 0) {
        return {-1.0, -1.0};
    }
    QRectF target = bounds;
    const auto sourceAspect = static_cast<qreal>(width) / static_cast<qreal>(height);
    const auto targetAspect = target.width() / target.height();
    if (sourceAspect > targetAspect) {
        const auto fittedHeight = target.width() / sourceAspect;
        target.setY((target.height() - fittedHeight) / 2.0);
        target.setHeight(fittedHeight);
    } else {
        const auto fittedWidth = target.height() * sourceAspect;
        target.setX((target.width() - fittedWidth) / 2.0);
        target.setWidth(fittedWidth);
    }
    if (x < target.left() || y < target.top() || x >= target.right() || y >= target.bottom()) {
        return {-1.0, -1.0};
    }
    return {
        (x - target.left()) / target.width(),
        (y - target.top()) / target.height()};
}

bool VideoPreviewItem::noteDeviceRemoved(long status) {
    if (SUCCEEDED(static_cast<HRESULT>(status))) return false;
    if (device_lost_) return true;
    device_lost_ = true;
    qWarning().noquote() << "D3D11 preview device removed"
                         << Qt::hex << static_cast<quint32>(status);
    QMetaObject::invokeMethod(this, [this] {
        emit deviceLostChanged();
        emit gpuDeviceRemoved();
    }, Qt::QueuedConnection);
    invalidateGraphics();
    return true;
}

QSGNode* VideoPreviewItem::updatePaintNode(QSGNode* oldNode, UpdatePaintNodeData*) {
    auto* root = oldNode != nullptr ? oldNode : new QSGNode();
    auto* node = static_cast<QSGSimpleTextureNode*>(root->firstChild());
    ffgui::PreviewVideoFrame next;
    {
        std::scoped_lock lock(frame_mutex_);
        if (pending_frame_.serial != 0 && pending_frame_.serial != rendered_serial_) {
            next = pending_frame_;
        }
    }
    if (next.serial != 0 && window() != nullptr) {
        if (rendered_serial_ == 0) {
            qInfo().noquote() << "first in-process preview render attempt"
                              << "serial=" << next.serial
                              << "cpu=" << (next.cpu_pixels != nullptr)
                              << "size=" << next.width << "x" << next.height;
        }
        QSGTexture* texture = nullptr;
        bool reusedBridgeTexture = false;
        if (next.cpu_pixels != nullptr && !next.cpu_pixels->empty() &&
            next.width > 0 && next.height > 0 && next.cpu_stride >= next.width * 4) {
            const QImage image(
                next.cpu_pixels->data(),
                static_cast<int>(next.width),
                static_cast<int>(next.height),
                static_cast<qsizetype>(next.cpu_stride),
                QImage::Format_ARGB32);
            texture = window()->createTextureFromImage(image);
        } else if (next.texture != nullptr) {
            auto* qtDevice = reinterpret_cast<ID3D11Device*>(devicePointer());
            if (qtDevice != nullptr &&
                noteDeviceRemoved(static_cast<long>(qtDevice->GetDeviceRemovedReason()))) {
                return root;
            }
            if (next.device != qtDevice || qtDevice == nullptr) return root;
            auto* sourceTexture = static_cast<ID3D11Texture2D*>(next.texture);
            D3D11_TEXTURE2D_DESC sourceDescription{};
            sourceTexture->GetDesc(&sourceDescription);
            const bool directlyShareable =
                sourceDescription.Format == DXGI_FORMAT_R8G8B8A8_UNORM &&
                sourceDescription.ArraySize == 1 &&
                sourceDescription.MipLevels == 1 &&
                next.texture_subresource == 0 &&
                (sourceDescription.BindFlags & D3D11_BIND_SHADER_RESOURCE) != 0;
            if (directlyShareable) {
                texture = QNativeInterface::QSGD3D11Texture::fromNative(
                    sourceTexture,
                    window(),
                    QSize(static_cast<int>(next.width), static_cast<int>(next.height)));
            } else if (display_texture_ == nullptr) {
                D3D11_TEXTURE2D_DESC displayDescription{};
                displayDescription.Width = next.width;
                displayDescription.Height = next.height;
                displayDescription.MipLevels = 1;
                displayDescription.ArraySize = 1;
                displayDescription.Format = sourceDescription.Format;
                displayDescription.SampleDesc.Count = 1;
                displayDescription.Usage = D3D11_USAGE_DEFAULT;
                displayDescription.BindFlags = D3D11_BIND_SHADER_RESOURCE;
                const auto created = qtDevice->CreateTexture2D(
                    &displayDescription, nullptr, &display_texture_);
                if (noteDeviceRemoved(static_cast<long>(created)) ||
                    FAILED(created) || display_texture_ == nullptr) {
                    qWarning().noquote() << "D3D11 preview bridge texture creation failed"
                                         << Qt::hex << created;
                    return root;
                }
                qInfo().noquote() << "D3D11 preview bridge created"
                                  << "source_format=" << sourceDescription.Format
                                  << "source_bind=" << sourceDescription.BindFlags
                                  << "source_array=" << sourceDescription.ArraySize
                                  << "source_mips=" << sourceDescription.MipLevels
                                  << "subresource=" << next.texture_subresource
                                  << "display_format=" << displayDescription.Format
                                  << "display_bind=" << displayDescription.BindFlags;
            }
            if (!directlyShareable) {
                ID3D11DeviceContext* context = nullptr;
                qtDevice->GetImmediateContext(&context);
                if (context == nullptr) return root;
                context->CopySubresourceRegion(
                    display_texture_,
                    0,
                    0,
                    0,
                    0,
                    sourceTexture,
                    next.texture_subresource,
                    nullptr);
                context->Release();
                if (noteDeviceRemoved(static_cast<long>(qtDevice->GetDeviceRemovedReason()))) {
                    return root;
                }
                if (node == nullptr) {
                    texture = QNativeInterface::QSGD3D11Texture::fromNative(
                        display_texture_,
                        window(),
                        QSize(static_cast<int>(next.width), static_cast<int>(next.height)));
                } else {
                    reusedBridgeTexture = true;
                }
            }
        }
        if (texture != nullptr || reusedBridgeTexture) {
            if (node == nullptr) {
                node = new QSGSimpleTextureNode();
                node->setTexture(texture);
                node->setOwnsTexture(true);
                node->setFiltering(QSGTexture::Linear);
                root->appendChildNode(node);
            } else if (texture != nullptr) {
                // Keep the scene-graph node alive while CPU/cached skim frames change.
                // Removing and recreating the node for every thumbnail exposed the
                // clear color between frames and made the whole viewer flash.
                auto* previousTexture = node->texture();
                node->setOwnsTexture(false);
                node->setTexture(texture);
                node->setOwnsTexture(true);
                node->setFiltering(QSGTexture::Linear);
                delete previousTexture;
            }
            constexpr std::uint64_t kCachedSkimSerial = 1ULL << 63;
            const bool cachedSkim = next.serial >= kCachedSkimSerial;
            {
                std::scoped_lock lock(frame_mutex_);
                if (!cachedSkim || layout_width_ == 0 || layout_height_ == 0) {
                    layout_width_ = next.width;
                    layout_height_ = next.height;
                }
                render_frame_ = std::move(next);
                rendered_serial_ = render_frame_.serial;
            }
            emit framePresented(rendered_serial_);
            if (rendered_serial_ <= 2) {
                qInfo().noquote() << "in-process preview frame presented"
                                  << "serial=" << rendered_serial_;
            }
        } else if (rendered_serial_ == 0) {
            qWarning().noquote() << "in-process preview texture creation failed"
                                 << "serial=" << next.serial;
        }
    }

    QRectF target = boundingRect();
    std::uint32_t layoutWidth = 0;
    std::uint32_t layoutHeight = 0;
    {
        std::scoped_lock lock(frame_mutex_);
        layoutWidth = layout_width_ != 0 ? layout_width_ : render_frame_.width;
        layoutHeight = layout_height_ != 0 ? layout_height_ : render_frame_.height;
    }
    if (layoutWidth > 0 && layoutHeight > 0 && target.height() > 0) {
        const auto sourceAspect = static_cast<qreal>(layoutWidth) /
            static_cast<qreal>(layoutHeight);
        const auto targetAspect = target.width() / target.height();
        if (sourceAspect > targetAspect) {
            const auto fittedHeight = target.width() / sourceAspect;
            target.setY((target.height() - fittedHeight) / 2.0);
            target.setHeight(fittedHeight);
        } else {
            const auto fittedWidth = target.height() * sourceAspect;
            target.setX((target.width() - fittedWidth) / 2.0);
            target.setWidth(fittedWidth);
        }
    }
    if (node != nullptr) node->setRect(target);
    return root;
}

void VideoPreviewItem::releaseResources() {
    std::scoped_lock lock(frame_mutex_);
    pending_frame_ = {};
    render_frame_ = {};
    rendered_serial_ = 0;
    layout_width_ = 0;
    layout_height_ = 0;
}

void VideoPreviewItem::initializeGraphics() {
    auto* itemWindow = window();
    if (itemWindow == nullptr ||
        itemWindow->rendererInterface()->graphicsApi() != QSGRendererInterface::Direct3D11) {
        return;
    }
    auto* device = static_cast<ID3D11Device*>(itemWindow->rendererInterface()->getResource(
        itemWindow, QSGRendererInterface::DeviceResource));
    if (device == nullptr) return;
    ID3D11Multithread* multithread = nullptr;
    if (SUCCEEDED(device->QueryInterface(
            __uuidof(ID3D11Multithread), reinterpret_cast<void**>(&multithread))) &&
        multithread != nullptr) {
        multithread->SetMultithreadProtected(TRUE);
        multithread->Release();
    } else {
        qWarning().noquote() << "Qt D3D11 device does not expose multithread protection";
    }
    {
        std::scoped_lock lock(device_mutex_);
        if (device_ == device) return;
        if (device_ != nullptr) device_->Release();
        device_ = device;
        device_->AddRef();
    }
    QMetaObject::invokeMethod(this, [this, device] {
        emit gpuReadyChanged();
        emit d3d11DeviceReady(reinterpret_cast<quintptr>(device));
    }, Qt::QueuedConnection);
}

void VideoPreviewItem::invalidateGraphics() {
    if (display_texture_ != nullptr) {
        display_texture_->Release();
        display_texture_ = nullptr;
    }
    ID3D11Device* oldDevice = nullptr;
    {
        std::scoped_lock lock(device_mutex_);
        oldDevice = std::exchange(device_, nullptr);
    }
    if (oldDevice != nullptr) oldDevice->Release();
}
