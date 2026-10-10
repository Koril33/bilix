"""Automatic GUI reads always use fake credentials and local test doubles."""

import pytest


@pytest.fixture(autouse=True)
def offline_account_and_dialogs(monkeypatch):
    pytest.importorskip("PySide6")
    from djhx_bilix.bilibili.client import BilibiliClient
    from djhx_bilix.errors import NetworkError
    from djhx_bilix.gui import app

    monkeypatch.setattr(app, "run_status", lambda emit, cancel: {"logged_in": False})

    def no_live_fetch(*args, **kwargs):
        raise NetworkError("离线测试未设置读取结果")

    monkeypatch.setattr(BilibiliClient, "fetch", no_live_fetch)
    monkeypatch.setattr(
        app.QMessageBox, "question", lambda *args, **kwargs: app.QMessageBox.StandardButton.Yes
    )
