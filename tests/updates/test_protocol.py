import copy

import pytest

from djhx_bilix.updater.protocol import (
    UpdateError,
    read_json,
    safe_download_url,
    verify_bundle,
    verify_signed,
)


def test_valid_bundle_and_exact_bytes_signature(signed_update):
    value = signed_update
    channel, artifact = verify_bundle(value["blobs"], "windows-x64-portable")
    assert channel["metadata_sequence"] == 10
    artifact.verify_file(value["directory"] / artifact.filename)
    with pytest.raises(UpdateError, match="签名"):
        verify_signed(value["blobs"]["stable.json"] + b" ", value["blobs"]["stable.json.sig"])
    with pytest.raises(UpdateError, match="信任"):
        verify_signed(value["blobs"]["stable.json"], value["blobs"]["stable.json.sig"], {})


@pytest.mark.parametrize("change", ["schema", "product", "channel", "arch", "filename", "urls"])
def test_signed_but_incompatible_metadata_is_rejected(signed_update, change):
    manifest = copy.deepcopy(signed_update["manifest"])
    if change in ("schema", "product", "channel"):
        manifest[change] = 9 if change == "schema" else "wrong"
    elif change == "arch":
        manifest["artifacts"][0][change] = "arm64"
    elif change == "filename":
        manifest["artifacts"][0][change] = "../target.exe"
    else:
        manifest["artifacts"][0][change][0] = "https://other.example/update.exe"
    with pytest.raises(UpdateError):
        verify_bundle(signed_update["bundle"](manifest), "windows-x64-portable")


def test_sequence_rollback_and_manifest_binding(signed_update):
    with pytest.raises(UpdateError, match="倒退"):
        verify_bundle(signed_update["blobs"], "windows-x64-portable", sequence=11)
    with pytest.raises(UpdateError, match="序号"):
        verify_bundle(
            signed_update["blobs"], "windows-x64-portable", sequence=10, previous_hash="0" * 64
        )
    blobs = dict(signed_update["blobs"])
    blobs["update-manifest.json"] += b" "
    blobs["update-manifest.json.sig"] = signed_update["sign"](blobs["update-manifest.json"])
    with pytest.raises(UpdateError, match="绑定"):
        verify_bundle(blobs, "windows-x64-portable")


def test_duplicate_fields_rejected_before_use():
    with pytest.raises(UpdateError, match="重复"):
        read_json(b'{"schema": 1, "schema": 1}')


@pytest.mark.parametrize(
    "url",
    [
        "http://bilix.djhx.site/a",
        "https://evil.example/a",
        "https://user:pass@github.com/a",
        "https://github.com:80/a",
    ],
)
def test_unsafe_redirect_rejected(url):
    with pytest.raises(UpdateError):
        safe_download_url(url)


def test_github_asset_redirect_supported():
    assert safe_download_url("https://release-assets.githubusercontent.com/a?sig=x")
