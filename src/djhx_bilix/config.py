"""Explicit configuration loading; importing the package never creates directories."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_downloads_path

from .errors import InputError


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    download_dir: Path
    ffmpeg: str | None = None

    @property
    def token_file(self) -> Path:
        return self.config_dir / "token.txt"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"


def load_settings() -> Settings:
    config_dir = Path(
        os.environ.get("BILIX_CONFIG_DIR")
        or user_config_path(appname="djhx-bilix", appauthor="djhx")
    ).expanduser()
    values = {}
    config_file = config_dir / "config.toml"
    if config_file.is_file():
        try:
            values = tomllib.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise InputError(
                "config.toml 无法读取或格式错误，请使用 blx config 查看配置位置"
            ) from None
    for key in ("download_dir", "ffmpeg"):
        if key in values and (not isinstance(values[key], str) or not values[key].strip()):
            raise InputError(f"config.toml 中的 {key} 必须是非空字符串")
    download_dir = Path(
        os.environ.get("BILIX_DOWNLOAD_DIR")
        or values.get("download_dir")
        or user_downloads_path() / "djhx-bilix"
    ).expanduser()
    ffmpeg = os.environ.get("BILIX_FFMPEG") or values.get("ffmpeg")
    return Settings(config_dir, download_dir, ffmpeg)
