"""State colors remain readable across application palettes."""

from PySide6.QtGui import QColor, QPalette


def state_color(state, palette):
    if palette.color(QPalette.ColorRole.Highlight).name() == "#ffff00":
        return palette.color(QPalette.ColorRole.Text)
    dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
    colors = {
        "completed": ("#13713d", "#75dba1"),
        "failed": ("#b12626", "#ff9292"),
        "skipped": ("#59616b", "#aeb7c3"),
        "canceled": ("#59616b", "#aeb7c3"),
        "replace": ("#995400", "#ffd17d"),
    }
    return (
        QColor(colors[state][int(dark)])
        if state in colors
        else palette.color(QPalette.ColorRole.Text)
    )
