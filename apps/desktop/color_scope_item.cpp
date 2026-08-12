#include "color_scope_item.hpp"

#include <QImage>
#include <QPainter>
#include <QPainterPath>

#include <algorithm>
#include <array>
#include <cmath>

namespace {

int alpha_for(std::uint16_t count, std::uint16_t maximum) {
    if (count == 0 || maximum == 0) return 0;
    return std::clamp(static_cast<int>(std::lround(
        32.0 + 223.0 * std::sqrt(static_cast<double>(count) / maximum))), 0, 255);
}

std::uint16_t maximum_of(const std::vector<std::uint16_t>& values) {
    return values.empty() ? 0 : *std::ranges::max_element(values);
}

}  // namespace

ColorScopeItem::ColorScopeItem(QQuickItem* parent) : QQuickPaintedItem(parent) {
    setAntialiasing(false);
    setRenderTarget(QQuickPaintedItem::FramebufferObject);
}

void ColorScopeItem::setMode(int mode) {
    const auto clamped = std::clamp(mode, 0, 3);
    if (mode_ == clamped) return;
    mode_ = clamped;
    emit modeChanged();
    update();
}

bool ColorScopeItem::hasSignal() const {
    std::scoped_lock lock(analysis_mutex_);
    return analysis_.has_value() && analysis_->sampled_pixels > 0;
}

void ColorScopeItem::submitAnalysis(ffgui::ScopeAnalysis analysis) {
    const auto hadSignal = hasSignal();
    {
        std::scoped_lock lock(analysis_mutex_);
        analysis_ = std::move(analysis);
    }
    if (hadSignal != hasSignal()) emit hasSignalChanged();
    update();
}

void ColorScopeItem::paint(QPainter* painter) {
    painter->fillRect(boundingRect(), QColor("#080b0f"));
    std::optional<ffgui::ScopeAnalysis> analysis;
    {
        std::scoped_lock lock(analysis_mutex_);
        analysis = analysis_;
    }
    const auto bounds = boundingRect().adjusted(8, 8, -8, -8);
    paintGrid(*painter, bounds);
    if (!analysis.has_value() || analysis->sampled_pixels == 0) return;
    switch (mode_) {
    case 0: paintWaveform(*painter, bounds, *analysis); break;
    case 1: paintParade(*painter, bounds, *analysis); break;
    case 2: paintVectorscope(*painter, bounds, *analysis); break;
    case 3: paintHistogram(*painter, bounds, *analysis); break;
    default: break;
    }
}

void ColorScopeItem::paintGrid(QPainter& painter, const QRectF& bounds) const {
    painter.setPen(QPen(QColor(83, 98, 115, 75), 1));
    for (int division = 0; division <= 4; ++division) {
        const auto x = bounds.left() + bounds.width() * division / 4.0;
        const auto y = bounds.top() + bounds.height() * division / 4.0;
        painter.drawLine(QPointF(x, bounds.top()), QPointF(x, bounds.bottom()));
        painter.drawLine(QPointF(bounds.left(), y), QPointF(bounds.right(), y));
    }
}

void ColorScopeItem::paintWaveform(
    QPainter& painter, const QRectF& bounds, const ffgui::ScopeAnalysis& analysis) const {
    QImage image(static_cast<int>(ffgui::ScopeAnalysis::waveform_width),
                 static_cast<int>(ffgui::ScopeAnalysis::waveform_height),
                 QImage::Format_ARGB32_Premultiplied);
    image.fill(Qt::transparent);
    const auto maximum = maximum_of(analysis.waveform);
    for (std::size_t y = 0; y < ffgui::ScopeAnalysis::waveform_height; ++y) {
        auto* row = reinterpret_cast<QRgb*>(image.scanLine(static_cast<int>(y)));
        for (std::size_t x = 0; x < ffgui::ScopeAnalysis::waveform_width; ++x) {
            const auto alpha = alpha_for(
                analysis.waveform[y * ffgui::ScopeAnalysis::waveform_width + x], maximum);
            row[x] = qRgba(184, 255, 218, alpha);
        }
    }
    painter.drawImage(bounds, image);
}

void ColorScopeItem::paintParade(
    QPainter& painter, const QRectF& bounds, const ffgui::ScopeAnalysis& analysis) const {
    constexpr std::array<QColor, 3> colors{QColor(255, 80, 88), QColor(78, 235, 138),
                                           QColor(76, 145, 255)};
    for (std::size_t channel = 0; channel < 3; ++channel) {
        QImage image(static_cast<int>(ffgui::ScopeAnalysis::waveform_width),
                     static_cast<int>(ffgui::ScopeAnalysis::waveform_height),
                     QImage::Format_ARGB32_Premultiplied);
        image.fill(Qt::transparent);
        const auto maximum = maximum_of(analysis.rgb_parade[channel]);
        for (std::size_t y = 0; y < ffgui::ScopeAnalysis::waveform_height; ++y) {
            auto* row = reinterpret_cast<QRgb*>(image.scanLine(static_cast<int>(y)));
            for (std::size_t x = 0; x < ffgui::ScopeAnalysis::waveform_width; ++x) {
                const auto alpha = alpha_for(
                    analysis.rgb_parade[channel][
                        y * ffgui::ScopeAnalysis::waveform_width + x], maximum);
                row[x] = qRgba(colors[channel].red(), colors[channel].green(),
                               colors[channel].blue(), alpha);
            }
        }
        auto target = bounds;
        target.setLeft(bounds.left() + bounds.width() * static_cast<qreal>(channel) / 3.0);
        target.setWidth(bounds.width() / 3.0);
        painter.drawImage(target.adjusted(2, 0, -2, 0), image);
    }
}

void ColorScopeItem::paintVectorscope(
    QPainter& painter, const QRectF& bounds, const ffgui::ScopeAnalysis& analysis) const {
    const auto edge = std::min(bounds.width(), bounds.height());
    const QRectF target(bounds.center().x() - edge / 2.0, bounds.center().y() - edge / 2.0,
                        edge, edge);
    painter.setPen(QPen(QColor(100, 118, 137, 100), 1));
    painter.drawEllipse(target.adjusted(1, 1, -1, -1));
    QImage image(static_cast<int>(ffgui::ScopeAnalysis::vectorscope_size),
                 static_cast<int>(ffgui::ScopeAnalysis::vectorscope_size),
                 QImage::Format_ARGB32_Premultiplied);
    image.fill(Qt::transparent);
    const auto maximum = maximum_of(analysis.vectorscope);
    for (std::size_t y = 0; y < ffgui::ScopeAnalysis::vectorscope_size; ++y) {
        auto* row = reinterpret_cast<QRgb*>(image.scanLine(static_cast<int>(y)));
        for (std::size_t x = 0; x < ffgui::ScopeAnalysis::vectorscope_size; ++x) {
            const auto alpha = alpha_for(
                analysis.vectorscope[y * ffgui::ScopeAnalysis::vectorscope_size + x], maximum);
            const auto cb = static_cast<float>(x) /
                (ffgui::ScopeAnalysis::vectorscope_size - 1) - 0.5F;
            const auto cr = 0.5F - static_cast<float>(y) /
                (ffgui::ScopeAnalysis::vectorscope_size - 1);
            const auto red = std::clamp(0.5F + 1.5748F * cr, 0.0F, 1.0F);
            const auto blue = std::clamp(0.5F + 1.8556F * cb, 0.0F, 1.0F);
            const auto green = std::clamp(
                0.5F - 0.1873F * cb - 0.4681F * cr, 0.0F, 1.0F);
            row[x] = qRgba(static_cast<int>(red * 255), static_cast<int>(green * 255),
                           static_cast<int>(blue * 255), alpha);
        }
    }
    painter.drawImage(target, image);
}

void ColorScopeItem::paintHistogram(
    QPainter& painter, const QRectF& bounds, const ffgui::ScopeAnalysis& analysis) const {
    const std::array<QColor, 4> colors{QColor(255, 72, 80, 180), QColor(74, 234, 132, 180),
                                      QColor(72, 136, 255, 180), QColor(235, 241, 248, 210)};
    std::uint32_t maximum = 1;
    for (const auto& channel : analysis.histogram) {
        maximum = std::max(maximum, *std::ranges::max_element(channel));
    }
    for (std::size_t channel = 0; channel < analysis.histogram.size(); ++channel) {
        QPainterPath path;
        for (std::size_t bin = 0; bin < ffgui::ScopeAnalysis::histogram_bins; ++bin) {
            const auto x = bounds.left() + bounds.width() * bin /
                (ffgui::ScopeAnalysis::histogram_bins - 1);
            const auto normalized = std::log1p(analysis.histogram[channel][bin]) /
                std::log1p(maximum);
            const auto y = bounds.bottom() - bounds.height() * normalized;
            if (bin == 0) path.moveTo(x, y); else path.lineTo(x, y);
        }
        painter.setPen(QPen(colors[channel], channel == 3 ? 1.5 : 1.0));
        painter.drawPath(path);
    }
}
