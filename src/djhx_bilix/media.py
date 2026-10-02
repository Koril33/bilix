"""FFmpeg discovery, complete packet scans, timeline checks and muxing."""

import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from .errors import MediaError


def find_ffmpeg(configured: str | None = None) -> Path:
    if configured:
        executable = shutil.which(configured) or str(Path(configured).expanduser())
        if Path(executable).is_file():
            return Path(executable).resolve()
        raise MediaError("指定的 FFmpeg 不存在，请检查 --ffmpeg 或 BILIX_FFMPEG")
    if os.name == "nt":
        bundled = Path(str(resources.files("djhx_bilix").joinpath("assets", "ffmpeg.exe")))
        if bundled.is_file():
            return bundled
    executable = shutil.which("ffmpeg")
    if executable:
        return Path(executable)
    raise MediaError("未找到 FFmpeg，请安装后加入 PATH，或通过 --ffmpeg 指定路径")


class FFmpeg:
    def __init__(self, executable: Path):
        self.executable = executable

    def _run(self, arguments: list[str]) -> str:
        command = [str(self.executable), "-hide_banner", "-nostdin", *arguments]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise MediaError("无法运行 FFmpeg，或媒体处理超过 10 分钟") from None
        if result.returncode:
            # Never echo stderr: it may contain signed URLs or unsanitized input metadata.
            raise MediaError("FFmpeg 检测到无效/残缺媒体，或处理失败；临时文件已保留")
        return result.stdout

    def check_stream(self, source: Path, target: Path, kind: str, expected: float) -> float:
        """Read every packet into a checked MP4 and measure the last packet timestamp.

        Header duration alone is insufficient: a truncated MP4 can advertise full duration.
        Stream copy also supports HEVC/AV1 with the bundled mux-only FFmpeg.
        """
        progress_file = target.with_suffix(".progress.txt")
        self._run(
            [
                "-v",
                "error",
                "-xerror",
                "-err_detect",
                "explode",
                "-y",
                "-i",
                str(source),
                "-map",
                f"0:{kind}:0",
                "-c",
                "copy",
                # MP4 otherwise silently drops Dolby Vision's dvcC/dvvC record.
                "-strict",
                "unofficial",
                "-progress",
                str(progress_file),
                str(target),
            ]
        )
        times = []
        for line in progress_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("out_time_us="):
                try:
                    times.append(int(line.split("=", 1)[1]) / 1_000_000)
                except ValueError:
                    pass
        duration = max(times, default=0)
        if not target.is_file() or target.stat().st_size == 0 or duration <= 0:
            raise MediaError("未能验证媒体流时长；临时文件已保留")
        if expected and abs(duration - expected) > 2:
            raise MediaError(f"媒体流时长不完整（预期 {expected:.1f} 秒，实际 {duration:.1f} 秒）")
        return duration

    def mux(self, video: Path, audio: Path, output: Path) -> None:
        self._run(
            [
                "-v",
                "error",
                "-xerror",
                "-err_detect",
                "explode",
                "-y",
                "-i",
                str(video),
                "-i",
                str(audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c",
                "copy",
                "-strict",
                "unofficial",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        if not output.is_file() or output.stat().st_size == 0:
            raise MediaError("FFmpeg 未生成有效输出")

    def version(self) -> str:
        # Version output is diagnostic metadata and contains no credentials.
        result = subprocess.run(
            [str(self.executable), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        if result.returncode:
            raise MediaError("FFmpeg 启动失败")
        return result.stdout.splitlines()[0]
