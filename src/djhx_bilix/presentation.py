"""Rich presentation isolated from network and download operations."""

from contextlib import contextmanager

from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

from .models import CODECS, QUALITY_NAMES, VideoInfo

console = Console(highlight=False)
error_console = Console(stderr=True, highlight=False)


def show_info(info: VideoInfo) -> None:
    text = Text(f"{info.title}\n{info.url}\n")
    text.append(f"BV: {info.bvid or '—'}  CID: {info.cid or '—'}  时长: {info.duration:.1f}s\n")
    if info.owner:
        text.append(f"UP 主: {info.owner}\n")
    if info.is_preview:
        text.append("当前仅有试看权限，下载器不会将其当作正片\n", style="yellow")
    if info.is_drm:
        text.append(
            "播放接口标记该媒体为 DRM 保护，当前不支持下载；请使用官方客户端播放\n", style="yellow"
        )
    if info.description:
        text.append(info.description + "\n")
    table = Table(title="清晰度与当前账号可获取的编码", expand=False)
    table.add_column("ID")
    table.add_column("清晰度")
    table.add_column("编码 / 权限")
    qualities = sorted(
        set(info.advertised_qualities) | {s.quality for s in info.videos}, reverse=True
    )
    for quality in qualities:
        codecs = sorted(
            {CODECS.get(s.codec, str(s.codec)) for s in info.videos if s.quality == quality}
        )
        table.add_row(
            str(quality),
            QUALITY_NAMES.get(quality, str(quality)),
            " / ".join(codecs) or "当前不可获取，可能需要登录或会员",
        )
    parts = Table(title=f"选集（{len(info.pages)}）")
    parts.add_column("P")
    parts.add_column("标题")
    parts.add_column("时长")
    for page in info.pages:
        parts.add_row(str(page.number), page.title, f"{page.duration:.0f}s")
    audio = Table(title="当前账号可获取的音轨")
    audio.add_column("ID")
    audio.add_column("格式")
    audio.add_column("码率")
    for stream in sorted(info.audios, key=lambda s: (s.audio_kind, -s.bandwidth)):
        audio.add_row(
            str(stream.quality), stream.audio_kind.upper(), f"{stream.bandwidth / 1000:.0f} kbps"
        )
    group = Group(text, table, audio, parts) if info.pages else Group(text, table, audio)
    console.print(Panel(group, title="BiliX · 视频信息", border_style="cyan", expand=False))


@contextmanager
def download_progress(quiet: bool = False):
    if quiet or not console.is_terminal:
        yield None
        return
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        tasks = {}

        def update(name, completed, total):
            if name not in tasks:
                tasks[name] = progress.add_task(name, total=total)
            progress.update(tasks[name], completed=completed, total=total)

        yield update
