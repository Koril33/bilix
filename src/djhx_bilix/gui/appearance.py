"""Small, shared Fusion theme and SVG icons, without extra widget libraries."""

from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionProgressBar

from .history import FEEDBACK_ROLE, NODE_ROLE, STREAMS_ROLE

ASSETS = Path(__file__).parents[1] / "assets"


def action_icon(name, palette):
    source = (ASSETS / f"action-{name}.svg").read_bytes()
    icon = QIcon()
    for mode, group in (
        (QIcon.Mode.Normal, QPalette.ColorGroup.Active),
        (QIcon.Mode.Disabled, QPalette.ColorGroup.Disabled),
    ):
        color = palette.color(group, QPalette.ColorRole.Text).name()
        renderer = QSvgRenderer(QByteArray(source.replace(b"COLOR", color.encode())))
        for scale in (1, 2):
            pixmap = QPixmap(20 * scale, 20 * scale)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap, mode)
    return icon


def apply_theme(application, mode="system"):
    # Keep borrowed PySide wrappers alive: a temporary accessibility wrapper can delete
    # the object returned by subsequent calls on some Qt/PySide builds.
    if not hasattr(application, "_bilix_style_hints"):
        application._bilix_style_hints = application.styleHints()
        application._bilix_accessibility = application._bilix_style_hints.accessibility()
    application.setStyle("Fusion")
    dark = mode == "dark" or (
        mode == "system" and application._bilix_style_hints.colorScheme() == Qt.ColorScheme.Dark
    )
    high = (
        application._bilix_accessibility.contrastPreference() == Qt.ContrastPreference.HighContrast
    )
    palette = application.style().standardPalette()
    if dark:
        for role, color in (
            (QPalette.ColorRole.Window, "#25282d"),
            (QPalette.ColorRole.Base, "#30343a"),
            (QPalette.ColorRole.AlternateBase, "#353a41"),
            (QPalette.ColorRole.Button, "#353a41"),
            (QPalette.ColorRole.Text, "#f2f3f5"),
            (QPalette.ColorRole.WindowText, "#f2f3f5"),
            (QPalette.ColorRole.ButtonText, "#f2f3f5"),
            (QPalette.ColorRole.ToolTipBase, "#30343a"),
            (QPalette.ColorRole.ToolTipText, "#f2f3f5"),
        ):
            palette.setColor(role, QColor(color))
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#89919c"))
    else:
        # Fusion's standard palette may follow a dark OS preference even when the
        # user explicitly chooses light. Set both surfaces and text in this branch.
        for role, color in (
            (QPalette.ColorRole.Window, "#f4f5f7"),
            (QPalette.ColorRole.Base, "#ffffff"),
            (QPalette.ColorRole.AlternateBase, "#eef1f5"),
            (QPalette.ColorRole.Button, "#e7eaf0"),
            (QPalette.ColorRole.Text, "#1f2530"),
            (QPalette.ColorRole.WindowText, "#1f2530"),
            (QPalette.ColorRole.ButtonText, "#1f2530"),
            (QPalette.ColorRole.ToolTipBase, "#ffffff"),
            (QPalette.ColorRole.ToolTipText, "#1f2530"),
            (QPalette.ColorRole.Light, "#ffffff"),
            (QPalette.ColorRole.Midlight, "#dde2ea"),
            (QPalette.ColorRole.Mid, "#ccd2dc"),
            (QPalette.ColorRole.Dark, "#939baa"),
            (QPalette.ColorRole.Shadow, "#647081"),
        ):
            palette.setColor(role, QColor(color))
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
        ):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#717a89"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#739fff" if dark else "#2859c5"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#101c35" if dark else "white"))
    if high:
        for role in (
            QPalette.ColorRole.Window,
            QPalette.ColorRole.Base,
            QPalette.ColorRole.AlternateBase,
            QPalette.ColorRole.Button,
            QPalette.ColorRole.ToolTipBase,
        ):
            palette.setColor(role, QColor("black"))
        for role in (
            QPalette.ColorRole.Text,
            QPalette.ColorRole.WindowText,
            QPalette.ColorRole.ButtonText,
            QPalette.ColorRole.ToolTipText,
        ):
            palette.setColor(role, QColor("white"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#ffff00"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("black"))
    application.setPalette(palette)
    application.setStyleSheet("""
        QPushButton, QToolButton { min-height: 28px; padding: 2px 9px; }
        QLineEdit, QComboBox { min-height: 28px; padding: 1px 5px; }
        QPushButton[primary="true"] { background: palette(highlight);
            color: palette(highlighted-text); border: 1px solid palette(highlight);
            border-radius: 6px; padding: 3px 15px; }
        QPushButton[primary="true"]:disabled { background: palette(button);
            color: palette(disabled, button-text); border-color: palette(mid); }
        QToolBar { spacing: 6px; padding: 5px; border: none; }
        QTreeView { border: none; }
        QTreeView::item { min-height: 36px; }
        QPlainTextEdit, QLineEdit, QComboBox { border-radius: 6px; }
        QStatusBar { border-top: 1px solid palette(mid); }
    """)


class TaskDelegate(QStyledItemDelegate):
    """Paint bounded per-stream progress and a selected-row menu without widgets."""

    show_feedback = True

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        lines = 3 if self.show_feedback else 2
        return QSize(size.width(), max(40, option.fontMetrics.height() * lines + 12))

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        node = index.data(NODE_ROLE)
        if index.column() == 3:
            if option.state & QStyle.StateFlag.State_Selected:
                painter.save()
                painter.setPen(option.palette.color(QPalette.ColorRole.HighlightedText))
                painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, "⋯")
                painter.restore()
            return
        streams = index.data(STREAMS_ROLE)
        if index.column() != 2 or not streams or node.state != "downloading":
            return
        available = option.rect.adjusted(4, 3, -4, -3)
        feedback = index.data(FEEDBACK_ROLE) if self.show_feedback else ""
        if feedback:
            available.setBottom(available.bottom() - option.fontMetrics.height() - 3)
        height = max(15, available.height() // len(streams))
        for row, (name, (done, total)) in enumerate(streams.items()):
            bar = QStyleOptionProgressBar()
            bar.rect = QRect(
                available.x(), available.y() + row * height, available.width(), height - 2
            )
            bar.palette = option.palette
            bar.minimum, bar.maximum = (0, 100) if total else (0, 0)
            bar.progress = min(100, done * 100 // total) if total else 0
            label = "视频" if name == "video" else "音频"
            value = f"{bar.progress}%" if total else f"{done / 1048576:.1f} MiB"
            bar.text, bar.textVisible = f"{label} {value}", True
            bar.state = option.state | QStyle.StateFlag.State_Horizontal
            bar.direction = Qt.LayoutDirection.LeftToRight
            bar.textAlignment = Qt.AlignmentFlag.AlignCenter
            option.widget.style().drawControl(
                QStyle.ControlElement.CE_ProgressBar, bar, painter, option.widget
            )
        if feedback:
            painter.save()
            selected = option.state & QStyle.StateFlag.State_Selected
            painter.setPen(
                option.palette.color(
                    QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
                )
            )
            text_rect = QRect(
                available.left(),
                available.bottom() + 2,
                available.width(),
                option.fontMetrics.height() + 2,
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft,
                option.fontMetrics.elidedText(
                    feedback, Qt.TextElideMode.ElideRight, text_rect.width()
                ),
            )
            painter.restore()
