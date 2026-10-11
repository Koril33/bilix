from threading import Event
from types import SimpleNamespace

from djhx_bilix.gui import updates
from djhx_bilix.gui.app import MainWindow


def fake_identity():
    return SimpleNamespace(artifact_id="windows-x64-portable")


def test_launch_check_timer_auto_download_and_ready_button(qtbot, monkeypatch):
    calls = []
    prepared = SimpleNamespace(artifact=SimpleNamespace(version="1.8.0"))

    class Client:
        def __init__(self, identity, cancel):
            calls.append(identity)

        def prepare(self, progress):
            progress("downloading", 5, 10)
            return prepared

    monkeypatch.setattr(updates, "distribution", fake_identity)
    monkeypatch.setattr(updates, "UpdateClient", Client)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window._prepared_update is prepared and window._update_thread is None)
    assert len(calls) == 1
    assert window._update_timer.interval() == 30 * 60 * 1000
    assert window._update_timer.isActive()
    assert window.update_button.isVisible()
    assert "就绪" in window.update_status.text()
    assert window._auto_update_enabled
    window._auto_update_enabled = False
    window._configure_update_timer()
    assert not window._update_timer.isActive()
    window._check_update()
    assert len(calls) == 1
    window._check_update(manual=True)
    qtbot.waitUntil(lambda: window._update_thread is None)
    assert len(calls) == 2


def test_update_click_waits_for_whole_media_worker_and_can_cancel_wait(qtbot, monkeypatch):
    monkeypatch.setattr(updates, "distribution", lambda: None)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window._prepared_update = SimpleNamespace(artifact=SimpleNamespace(version="1.8.0"))
    # The actual media QThread stays alive for the entire batch, including its remaining queue.
    window._thread = object()
    window._apply_update()
    assert window._update_install_pending
    assert window._update_thread is None
    assert "本批" in window.update_status.text()
    assert window.update_button.text() == "取消等待"
    window._apply_update()
    assert not window._update_install_pending
    window._thread = None


def test_tray_close_keeps_update_running_and_exit_cancels_it(qtbot, monkeypatch):
    monkeypatch.setattr(updates, "distribution", lambda: None)
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    cancel = Event()
    window._update_thread = SimpleNamespace(cancel=cancel)
    monkeypatch.setattr(window, "_tray_available", lambda: False)
    window.close()
    assert not cancel.is_set()
    window._request_exit()
    assert cancel.is_set()
    assert window._close_pending
    window._update_thread = None
    window.close()
