"""FFmpeg discovery, complete packet scans, timeline checks and muxing."""

import os
import shutil
import subprocess
import time
from importlib import resources
from pathlib import Path

from .errors import MediaError
from .operations import CancellationToken


def find_ffmpeg(configured: str | None = None) -> Path:
    if configured:
        executable = shutil.which(configured) or str(Path(configured).expanduser())
        if Path(executable).is_file():
            return Path(executable).resolve()
        raise MediaError(
            "指定的 FFmpeg 不存在，请检查 --ffmpeg 或 BILIX_FFMPEG", error_code="ffmpeg"
        )
    if os.name == "nt":
        bundled = Path(str(resources.files("djhx_bilix").joinpath("assets", "ffmpeg.exe")))
        if bundled.is_file():
            return bundled
    executable = shutil.which("ffmpeg")
    if executable:
        return Path(executable)
    raise MediaError(
        "未找到 FFmpeg，请安装后加入 PATH，或通过 --ffmpeg 指定路径", error_code="ffmpeg"
    )


class FFmpeg:
    def __init__(self, executable: Path):
        self.executable = executable

    def _run(self, arguments: list[str], *, cancel: CancellationToken | None = None) -> str:
        command = [str(self.executable), "-hide_banner", "-nostdin", *arguments]
        if cancel is not None:
            # The GUI must be able to stop an active scan or mux. FFmpeg writes
            # only to files here, so its output can be discarded without pipes
            # that might fill while the worker polls for cancellation.
            cancel.raise_if_cancelled()
            try:
                with subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                ) as process:
                    deadline = time.monotonic() + 600
                    while process.poll() is None:
                        if cancel.cancelled() or time.monotonic() >= deadline:
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=3)
                            if cancel.cancelled():
                                cancel.raise_if_cancelled()
                            raise MediaError(
                                "无法运行 FFmpeg，或媒体处理超过 10 分钟", error_code="ffmpeg"
                            )
                        cancel.wait(0.2)
                    cancel.raise_if_cancelled()
                    if process.returncode:
                        raise MediaError("FFmpeg 检测到无效/残缺媒体，或处理失败；临时文件已保留")
                    return ""
            except OSError:
                raise MediaError(
                    "无法运行 FFmpeg，或媒体处理超过 10 分钟", error_code="ffmpeg"
                ) from None
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
            raise MediaError(
                "无法运行 FFmpeg，或媒体处理超过 10 分钟", error_code="ffmpeg"
            ) from None
        if result.returncode:
            # Never echo stderr: it may contain signed URLs or unsanitized input metadata.
            raise MediaError("FFmpeg 检测到无效/残缺媒体，或处理失败；临时文件已保留")
        return result.stdout

    def check_stream(
        self,
        source: Path,
        target: Path,
        kind: str,
        expected: float,
        *,
        cancel: CancellationToken | None = None,
    ) -> float:
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
                "-f",
                "mp4",
                # MP4 otherwise silently drops Dolby Vision's dvcC/dvvC record.
                "-strict",
                "experimental",
                "-progress",
                str(progress_file),
                str(target),
            ],
            cancel=cancel,
        )
        if cancel:
            cancel.raise_if_cancelled()
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

    def mux(
        self,
        video: Path,
        audio: Path,
        output: Path,
        *,
        cancel: CancellationToken | None = None,
    ) -> None:
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
                "experimental",
                "-movflags",
                "+faststart",
                str(output),
            ],
            cancel=cancel,
        )
        if cancel:
            cancel.raise_if_cancelled()
        if not output.is_file() or output.stat().st_size == 0:
            raise MediaError("FFmpeg 未生成有效输出")

    def version(self) -> str:
        # Version output is diagnostic metadata and contains no credentials.
        try:
            result = subprocess.run(
                [str(self.executable), "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            raise MediaError("无法运行 FFmpeg，请检查程序路径和权限", error_code="ffmpeg") from None
        if result.returncode:
            raise MediaError("FFmpeg 启动失败", error_code="ffmpeg")
        return result.stdout.splitlines()[0]
