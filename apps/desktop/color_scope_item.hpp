#pragma once

#include "color/scope_analyzer.hpp"

#include <QQuickPaintedItem>
#include <QtQml/qqmlregistration.h>

#include <mutex>
#include <optional>

class ColorScopeItem : public QQuickPaintedItem {
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(int mode READ mode WRITE setMode NOTIFY modeChanged)
    Q_PROPERTY(bool hasSignal READ hasSignal NOTIFY hasSignalChanged)

public:
    explicit ColorScopeItem(QQuickItem* parent = nullptr);

    [[nodiscard]] int mode() const noexcept { return mode_; }
    void setMode(int mode);
    [[nodiscard]] bool hasSignal() const;
    void submitAnalysis(ffgui::ScopeAnalysis analysis);
    void paint(QPainter* painter) override;

signals:
    void modeChanged();
    void hasSignalChanged();

private:
    void paintGrid(QPainter& painter, const QRectF& bounds) const;
    void paintWaveform(QPainter& painter, const QRectF& bounds,
                       const ffgui::ScopeAnalysis& analysis) const;
    void paintParade(QPainter& painter, const QRectF& bounds,
                     const ffgui::ScopeAnalysis& analysis) const;
    void paintVectorscope(QPainter& painter, const QRectF& bounds,
                          const ffgui::ScopeAnalysis& analysis) const;
    void paintHistogram(QPainter& painter, const QRectF& bounds,
                        const ffgui::ScopeAnalysis& analysis) const;

    int mode_{};
    mutable std::mutex analysis_mutex_;
    std::optional<ffgui::ScopeAnalysis> analysis_;
};
