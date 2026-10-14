"""The selected output mode controls visible parameters and the submitted snapshot."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem

from djhx_bilix.errors import InputError
from djhx_bilix.gui.app import MainWindow


def test_download_mode_controls_and_cover_source_selection(qtbot, video_info):
    window = MainWindow()
    qtbot.addWidget(window)
    window.urls_edit.setPlainText(video_info.url)
    window._info_generation = window._input_generation
    window._parse_total = 1
    window.metadata_tree.addTopLevelItem(QTreeWidgetItem([video_info.url, ""]))
    window._on_event(dict(type="info", index=0, metadata=video_info.public_dict()))
    window._parse_complete = True
    modes = {
        value: window.mode_combo.findData(value)
        for value in ("merged", "audio", "video", "separate", "cover")
    }
    assert all(index >= 0 for index in modes.values())

    window.mode_combo.setCurrentIndex(modes["audio"])
    assert window.quality_combo.isHidden() and window.strict_check.isHidden()
    assert not window.audio_combo.isHidden()
    assert window._options(True).mode == "audio"

    window.mode_combo.setCurrentIndex(modes["video"])
    assert window.audio_combo.isHidden() and not window.quality_combo.isHidden()
    window.save_cover_check.setChecked(True)
    assert window._options(True).cover

    window.mode_combo.setCurrentIndex(modes["cover"])
    assert window.save_cover_check.isHidden()
    assert window.metadata_tree.topLevelItem(0).child(0).isHidden()
    assert window._inputs()[0].page is None
    assert "1 个封面" in window.parse_summary.text()
    assert window._options(True).mode == "cover"

    window.metadata_tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    with pytest.raises(InputError, match="勾选"):
        window._inputs()
