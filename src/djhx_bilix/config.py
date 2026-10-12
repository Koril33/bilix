"""Explicit configuration loading; importing the package never creates directories."""

import json
import os
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_downloads_path

from .errors import InputError

_UNCHANGED = object()


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    download_dir: Path
    ffmpeg: str | None = None
    file_download_dir: Path | None = None
    file_ffmpeg: str | None = None
    download_source: str = "默认值"
    ffmpeg_source: str = "自动查找"
    naming_template: str = "{title}"
    proxy: str | None = None
    concurrency: int = 1
    file_proxy: str | None = None

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
                "config.toml 无法读取或格式错误，请使用 blx config 查看配置位置",
                error_code="config",
                action="请修正 config.toml",
            ) from None
    for key in ("download_dir", "ffmpeg"):
        if key in values and (not isinstance(values[key], str) or not values[key].strip()):
            raise InputError(
                f"config.toml 中的 {key} 必须是非空字符串",
                error_code="config",
                action="请修正 config.toml",
            )
    download_dir = Path(
        os.environ.get("BILIX_DOWNLOAD_DIR")
        or values.get("download_dir")
        or user_downloads_path() / "djhx-bilix"
    ).expanduser()
    ffmpeg = os.environ.get("BILIX_FFMPEG") or values.get("ffmpeg")
    from .filenames import validate_template
    from .network import validate_proxy

    naming = values.get("naming_template", "{title}")
    validate_template(naming)
    concurrency = values.get("concurrency", 1)
    if type(concurrency) is not int or not 1 <= concurrency <= 4:
        raise InputError("同时下载数必须为 1 到 4 的整数", error_code="config")
    file_proxy = validate_proxy(values.get("proxy"))
    return Settings(
        config_dir,
        download_dir,
        ffmpeg,
        Path(values["download_dir"]).expanduser() if values.get("download_dir") else None,
        values.get("ffmpeg"),
        "BILIX_DOWNLOAD_DIR 环境变量"
        if os.environ.get("BILIX_DOWNLOAD_DIR")
        else "config.toml"
        if values.get("download_dir")
        else "默认值",
        "BILIX_FFMPEG 环境变量"
        if os.environ.get("BILIX_FFMPEG")
        else "config.toml"
        if values.get("ffmpeg")
        else "自动查找",
        naming,
        validate_proxy(os.environ.get("BILIX_PROXY") or file_proxy),
        concurrency,
        file_proxy,
    )


def save_settings(
    settings: Settings,
    *,
    download_dir: Path,
    ffmpeg: str | None,
    naming_template: str | None = None,
    proxy: str | None | object = _UNCHANGED,
    concurrency: int | None = None,
) -> Settings:
    """Atomically persist user settings; environment overrides still take precedence."""
    if not isinstance(download_dir, Path) or not str(download_dir).strip():
        raise InputError("下载目录必须是有效路径")
    if ffmpeg is not None and (not isinstance(ffmpeg, str) or not ffmpeg.strip()):
        raise InputError("FFmpeg 路径必须是非空字符串，或留空使用自动查找")
    from .filenames import validate_template
    from .network import validate_proxy

    naming_template = settings.naming_template if naming_template is None else naming_template
    validate_template(naming_template)
    proxy = settings.file_proxy if proxy is _UNCHANGED else validate_proxy(proxy)
    concurrency = settings.concurrency if concurrency is None else concurrency
    if type(concurrency) is not int or not 1 <= concurrency <= 4:
        raise InputError("同时下载数必须为 1 到 4 的整数")
    values = f"download_dir = {json.dumps(str(download_dir), ensure_ascii=False)}\n"
    if ffmpeg is not None:
        values += f"ffmpeg = {json.dumps(ffmpeg, ensure_ascii=False)}\n"
    values += f"naming_template = {json.dumps(naming_template, ensure_ascii=False)}\n"
    values += f"concurrency = {concurrency}\n"
    if proxy:
        values += f"proxy = {json.dumps(proxy, ensure_ascii=False)}\n"
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
    return Settings(
        settings.config_dir,
        download_dir,
        ffmpeg,
        naming_template=naming_template,
        proxy=proxy,
        concurrency=concurrency,
        file_proxy=proxy,
    )
