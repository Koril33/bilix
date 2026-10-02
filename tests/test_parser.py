import json

import pytest

from djhx_bilix.bilibili.parser import embedded_json, parse_video
from djhx_bilix.errors import BilixError

URL = "https://www.bilibili.com/video/BV1j4411W7F7"


def test_json_strings_with_braces_and_semicolons():
    value = {"title": 'a }; <b> " c', "nested": {"items": [1, 2]}}
    document = f"<script>window.__INITIAL_STATE__={json.dumps(value)};(function(){{}})</script>"
    assert embedded_json(document, "__INITIAL_STATE__") == value
    assert embedded_json('const playurlSSRData={"a":1};</script>', "playurlSSRData") == {"a": 1}


def test_malformed_json_fails_explicitly():
    with pytest.raises(BilixError):
        embedded_json("window.__playinfo__={bad};", "__playinfo__")


@pytest.mark.parametrize("shape", ["playinfo", "result", "raw"])
def test_playback_shapes(shape):
    play = {
        "timelength": 4000,
        "dash": {
            "video": [
                {
                    "id": 32,
                    "codecid": 7,
                    "baseUrl": "https://cdn/video",
                    "backupUrl": ["https://backup/video"],
                    "bandwidth": 100,
                }
            ],
            "audio": [{"id": 30280, "base_url": "https://cdn/audio", "bandwidth": 100}],
        },
    }
    data = (
        {"data": play}
        if shape == "playinfo"
        else (
            {"result": {"video_info": play}}
            if shape == "result"
            else {"raw": {"data": {"video_info": play}}}
        )
    )
    name = "__playinfo__" if shape == "playinfo" else "playurlSSRData"
    document = f"<title>A &amp; B</title><script>window.{name}={json.dumps(data)};</script>"
    info = parse_video(document, URL)
    assert info.duration == 4
    assert info.title == "A & B"
    assert len(info.videos[0].urls) == 2
    assert "https://cdn" not in json.dumps(info.public_dict())


def test_invalid_video_page():
    with pytest.raises(BilixError):
        parse_video("<title>404</title>", URL)
