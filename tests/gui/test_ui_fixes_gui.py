"""Small 1.7.5 regressions for the six reported desktop issues."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter, QStandardItemModel
from PySide6.QtWidgets import QApplication, QLabel, QStyleOptionViewItem

from djhx_bilix import __version__, tasks
from djhx_bilix.errors import NetworkError
from djhx_bilix.gui.app import MainWindow
from djhx_bilix.gui.appearance import apply_theme
from djhx_bilix.gui.history import NODE_ROLE, STREAMS_ROLE
from djhx_bilix.models import DownloadResult
from djhx_bilix.tasks import JobSpec


def window(qtbot):
    value = MainWindow()
    qtbot.addWidget(value)
    value.show()
    return value


@pytest.mark.parametrize("result", ["completed", "source_failed", "cleared"])
def test_notification_uses_readable_context_details(
    qtbot, monkeypatch, video_info, tmp_path, result
):
    value = window(qtbot)

    def fetch(*args):
        if result == "source_failed":
            raise NetworkError("读取失败")
        return video_info

    monkeypatch.setattr(tasks.BilibiliClient, "fetch", fetch)
    monkeypatch.setattr(
        tasks, "execute", lambda *a, **k: DownloadResult(tmp_path / "result.mp4", False)
    )
    value._start_download(specs=(JobSpec(video_info.url),))
    qtbot.waitUntil(lambda: value._thread is None)
    batch_id = next(iter(value.session.batches))
    node = (
        next(iter(value.history_model.tasks.values()))
        if value.history_model.tasks
        else value.history_model.roots[0]
    )
    value.jobs_view.setCurrentIndex(
        value.history_filter.mapFromSource(value.history_model.row_index(node))
    )
    value._open_details()
    expected = (
        value.details_summary.text(),
        value.info_text.toPlainText(),
        value.batch_text.toPlainText(),
    )
    value._details_dialog.reject()
    if result == "cleared":
        value._clear_records(frozenset({"completed", "discovered"}))
    value._last_notified_batch = batch_id
    value._notification_clicked()
    assert value._details_dialog.isVisible()
    assert not value.batch_text.toPlainText().lstrip().startswith("{")
    assert "来源" in value.batch_text.toPlainText()
    if result == "cleared":
        assert value.details_summary.text() == "本批下载记录已清除"
        assert not value.info_text.toPlainText()
    else:
        assert expected == (
            value.details_summary.text(),
            value.info_text.toPlainText(),
            value.batch_text.toPlainText(),
        )


@pytest.mark.parametrize("available", [True, False])
def test_title_close_keeps_worker_and_explicit_exit_stops_it(qtbot, monkeypatch, available):
    value = window(qtbot)
    monkeypatch.setattr(value, "_tray_available", lambda: available)
    monkeypatch.setattr(value.tray, "show", lambda: None)
    closed = []
    value.closed.connect(lambda: closed.append(True))
    value._start_operation("test", lambda emit, cancel: cancel.wait(2))
    try:
        value.close()
        qtbot.wait(20)
        assert not value._cancel.cancelled() and not value._close_pending and not closed
        assert value._in_tray == available
        assert not value.isVisible() if available else value.isVisible() and value.isMinimized()
        value._restore_main()
        value.exit_action.trigger()
        qtbot.waitUntil(lambda: value._thread is None and bool(closed))
        assert not value.isVisible()
    finally:
        if value._thread is not None:
            value._cancel_active()
            qtbot.waitUntil(lambda: value._thread is None)


def test_account_is_display_only_and_menu_has_one_native_indicator(qtbot):
    value = window(qtbot)
    value._set_account("已验证的会员账号", "已登录 · 用户 · 大会员")
    assert isinstance(value.account_status, QLabel)
    assert "大会员" in value.account_status.full_text
    assert value.account_status.toolTip() == "已验证的会员账号"
    assert value.selection_button.menu() is value.selection_menu
    assert value.selection_button.text() == "更多操作"
    assert value.login_action in value.account_menu.actions()
    assert value.tray_exit_action.text() == "退出"


def test_about_is_independent_and_contains_requested_metadata(qtbot):
    value = window(qtbot)
    value.about_action.trigger()
    assert value._about_dialog.isVisible() and not value._settings_dialog.isVisible()
    text = "\n".join(label.text() for label in value._about_dialog.findChildren(QLabel))
    for expected in (
        "BiliX",
        __version__,
        "https://djhx.site/project/bilix.html",
        "https://github.com/Koril33/bilix",
        "dingjinghui",
        "dingjinghui33@163.com",
    ):
        assert expected in text
    assert value.settings_tabs.tabText(2) == "诊断"
    value._about_dialog.reject()
    value._open_doctor()
    assert value._settings_dialog.isVisible() and not value._about_dialog.isVisible()
    qtbot.waitUntil(lambda: value._thread is None)


@pytest.mark.parametrize("scheme", [Qt.ColorScheme.Light, Qt.ColorScheme.Dark])
def test_audio_and_video_progress_fill_left_to_right(qtbot, scheme):
    application = QApplication.instance()
    previous = application.styleHints().colorScheme()
    application.styleHints().setColorScheme(scheme)
    apply_theme(application)
    value = window(qtbot)
    model = QStandardItemModel(1, 3)
    index = model.index(0, 2)
    model.setData(index, SimpleNamespace(state="downloading"), NODE_ROLE)
    model.setData(index, {"video": (50, 100), "audio": (50, 100)}, STREAMS_ROLE)
    option = QStyleOptionViewItem()
    option.initFrom(value.jobs_view)
    option.widget = value.jobs_view
    option.rect = QRect(0, 0, 240, 50)
    image = QImage(240, 50, QImage.Format.Format_RGB32)
    image.fill(value.jobs_view.palette().base().color())
    painter = QPainter(image)
    try:
        value.jobs_view.itemDelegate().paint(painter, option, index)
    finally:
        painter.end()
        application.styleHints().setColorScheme(previous)
        apply_theme(application)
    for y in (8, 30):
        left, right = image.pixelColor(20, y), image.pixelColor(220, y)
        assert left.blue() > left.red() + 30
        assert right.blue() < right.red() + 30
