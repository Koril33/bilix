"""Explicit configuration loading; importing the package never creates directories."""

import json
import os
import tempfile
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


def save_settings(settings: Settings, *, download_dir: Path, ffmpeg: str | None) -> Settings:
    """Atomically persist user settings; environment overrides still take precedence."""
    if not isinstance(download_dir, Path) or not str(download_dir).strip():
        raise InputError("下载目录必须是有效路径")
    if ffmpeg is not None and (not isinstance(ffmpeg, str) or not ffmpeg.strip()):
        raise InputError("FFmpeg 路径必须是非空字符串，或留空使用自动查找")
    values = f"download_dir = {json.dumps(str(download_dir), ensure_ascii=False)}\n"
    if ffmpeg is not None:
        values += f"ffmpeg = {json.dumps(ffmpeg, ensure_ascii=False)}\n"
    settings.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".config-", dir=settings.config_dir)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(values)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, settings.config_file)
    finally:
        temporary.unlink(missing_ok=True)
    return Settings(settings.config_dir, download_dir, ffmpeg)
