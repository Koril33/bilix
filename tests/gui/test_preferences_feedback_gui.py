"""GUI boundaries: preferences never mutate a submitted download or business config."""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from djhx_bilix.feedback import TransferSample
from djhx_bilix.gui.app import MainWindow
from djhx_bilix.gui.preferences import GuiPreferences


def test_theme_persistence_does_not_write_business_config(qtbot, settings):
    value = MainWindow()
    qtbot.addWidget(value)
    value.theme_combo.setCurrentIndex(value.theme_combo.findData("dark"))
    assert value._save_settings()
    assert not settings.config_file.exists()
    assert GuiPreferences().theme() == "dark"
    assert QApplication.palette().color(QPalette.ColorRole.Base).lightness() < 100
    value.theme_combo.setCurrentIndex(value.theme_combo.findData("light"))
    value._discard_gui_settings()
    assert value.theme_combo.currentData() == "dark"
    value.theme_combo.setCurrentIndex(value.theme_combo.findData("light"))
    assert value._save_settings()
    assert QApplication.palette().color(QPalette.ColorRole.Base).lightness() > 200
    assert QApplication.palette().color(QPalette.ColorRole.Text).lightness() < 100


def test_theme_can_be_saved_during_download(qtbot, settings):
    value = MainWindow()
    qtbot.addWidget(value)
    value._start_operation("test", lambda emit, cancel: cancel.wait(5))
    value.theme_combo.setCurrentIndex(value.theme_combo.findData("dark"))
    assert value._save_settings()
    assert not value.default_output_edit.isEnabled()
    assert not settings.config_file.exists()
    value._cancel_active()
    qtbot.waitUntil(lambda: value._thread is None)


def test_reset_preserves_update_account_and_business_preferences(qtbot, settings):
    value = MainWindow()
    qtbot.addWidget(value)
    value.auto_update_check.setChecked(False)
    value.tray_check.setChecked(False)
    value.theme_combo.setCurrentIndex(value.theme_combo.findData("dark"))
    assert value._save_settings()
    value._restore_interface_defaults()
    prefs = GuiPreferences()
    assert prefs.theme() == "system"
    assert not prefs.read("automaticUpdates", True, bool)
    assert not prefs.read("minimizeToTray", True, bool)
    assert not settings.config_file.exists()


def test_disabled_memory_uses_defaults_for_empty_draft(qtbot):
    value = MainWindow()
    qtbot.addWidget(value)
    value.quality_combo.setCurrentIndex(value.quality_combo.findData(80))
    value.strict_check.setChecked(True)
    value._remember_media_options()
    value.remember_check.setChecked(False)
    assert value._save_settings()
    value._open_draft(read_clipboard=False)
    assert value.quality_combo.currentData() is None
    assert not value.strict_check.isChecked()


def test_gui_and_rich_read_the_same_shared_values(qtbot, monkeypatch):
    from rich.progress import Task

    import djhx_bilix.feedback as feedback
    from djhx_bilix.feedback import TransferEstimator
    from djhx_bilix.presentation import SharedFeedbackColumn

    monkeypatch.setattr(feedback.time, "monotonic", lambda: 2.0)
    monitor = TransferEstimator()
    for name in ("video", "audio"):
        monitor.ingest(TransferSample(name, 1, 1, "receiving", 0, 6000, 0))
        monitor.ingest(TransferSample(name, 1, 2, "receiving", 2000, 6000, 2))
    task = Task(
        1, "video", 6000, 2000, lambda: 2.0, fields={"stream": "video", "estimator": monitor}
    )
    assert SharedFeedbackColumn(False).render(task).plain == "1000 B/s"
    assert SharedFeedbackColumn(True).render(task).plain == "约 5 秒"
    assert monitor.snapshot().speed == 2000


def test_shortcuts_have_list_scope_and_help_is_available(qtbot):
    from PySide6.QtCore import Qt

    value = MainWindow()
    qtbot.addWidget(value)
    for action, _, _ in value._list_shortcuts:
        assert action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
        assert not action.autoRepeat()
    value._open_shortcuts()
    assert value._shortcuts_dialog.isVisible()


def test_corrupt_business_config_does_not_block_gui_theme(qtbot, settings):
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    settings.config_file.write_text("broken = [", encoding="utf-8")
    value = MainWindow()
    qtbot.addWidget(value)
    value.theme_combo.setCurrentIndex(value.theme_combo.findData("dark"))
    assert value._save_settings()
    assert settings.config_file.read_text(encoding="utf-8") == "broken = ["
    assert GuiPreferences().theme() == "dark"


def test_preference_write_failure_rolls_back_unsaved_values(monkeypatch, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("a regular file", encoding="utf-8")
    monkeypatch.setenv("BILIX_CONFIG_DIR", str(blocked))
    value = GuiPreferences()
    assert not value.commit({"themeMode": "dark"})
    assert value.theme() == "system"


def test_invalid_preferences_and_corrupt_file_can_be_reset(monkeypatch, tmp_path):
    monkeypatch.setenv("BILIX_CONFIG_DIR", str(tmp_path))
    path = tmp_path / "gui.ini"
    path.write_text("[v1]\nthemeMode=sepia\nrememberMediaOptions=invalid\n", encoding="utf-8")
    value = GuiPreferences()
    assert value.theme() == "system"
    assert value.read("rememberMediaOptions", True, bool)
    path.write_text("[v1\nthemeMode=dark\n", encoding="utf-8")
    value.store.sync()
    assert value.status() == value.Status.FormatError
    assert value.reset_interface()
    assert value.theme() == "system"
    assert len(list(tmp_path.glob("gui.ini.corrupt-*.bak"))) == 1


def test_list_valued_theme_does_not_prevent_startup(qtbot):
    assert GuiPreferences().commit({"themeMode": ["light", "dark"]})
    value = MainWindow()
    qtbot.addWidget(value)
    assert value._theme_mode == "system"
    assert value.theme_combo.currentData() == "system"


def test_f1_shortcut_and_list_shortcut_do_not_escape_dialog(qtbot, monkeypatch):
    from PySide6.QtCore import Qt

    value = MainWindow()
    qtbot.addWidget(value)
    value.show()
    value.activateWindow()
    value.jobs_view.setFocus()
    qtbot.wait(50)
    qtbot.keyClick(value.jobs_view, Qt.Key.Key_F1)
    qtbot.waitUntil(lambda: value._shortcuts_dialog.isVisible())
    value._shortcuts_dialog.close()
    triggered = []
    value.details_action.triggered.connect(lambda: triggered.append(True))
    value.details_action.setEnabled(True)
    value._draft_dialog.show()
    value._draft_dialog.activateWindow()
    value.urls_edit.setFocus()
    qtbot.wait(50)
    qtbot.keyClick(value.urls_edit, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert not triggered
    qtbot.keyClick(value.urls_edit, Qt.Key.Key_F1)
    qtbot.waitUntil(lambda: value._shortcuts_dialog.isVisible())
