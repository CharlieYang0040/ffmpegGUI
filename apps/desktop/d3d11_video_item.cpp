#include "d3d11_video_item.hpp"

#include <QMetaObject>
#include <QImage>
#include <QDebug>
#include <QQuickWindow>
#include <QSGSimpleTextureNode>
#include <QSGRendererInterface>
#include <QtQuick/qsgtexture_platform.h>

#include <d3d11.h>

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
    update();
    if (window() != nullptr) {
        window()->update();
        window()->requestUpdate();
    }
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
            const auto qtDevice = reinterpret_cast<void*>(devicePointer());
            if (next.device != qtDevice) return root;
            texture = QNativeInterface::QSGD3D11Texture::fromNative(
                next.texture,
                window(),
                QSize(static_cast<int>(next.width), static_cast<int>(next.height)));
        }
        if (texture != nullptr) {
            if (node != nullptr) {
                root->removeChildNode(node);
                delete node;
            }
            node = new QSGSimpleTextureNode();
            node->setTexture(texture);
            node->setOwnsTexture(true);
            root->appendChildNode(node);
            render_frame_ = std::move(next);
            rendered_serial_ = render_frame_.serial;
            emit framePresented(rendered_serial_);
            if (rendered_serial_ == next.serial && next.serial <= 2) {
                qInfo().noquote() << "in-process preview frame presented"
                                  << "serial=" << rendered_serial_;
            }
        } else if (rendered_serial_ == 0) {
            qWarning().noquote() << "in-process preview texture creation failed"
                                 << "serial=" << next.serial;
        }
    }

    QRectF target = boundingRect();
    if (render_frame_.width > 0 && render_frame_.height > 0 && target.height() > 0) {
        const auto sourceAspect = static_cast<qreal>(render_frame_.width) /
            static_cast<qreal>(render_frame_.height);
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
    ID3D11Device* oldDevice = nullptr;
    {
        std::scoped_lock lock(device_mutex_);
        oldDevice = std::exchange(device_, nullptr);
    }
    if (oldDevice != nullptr) oldDevice->Release();
}
