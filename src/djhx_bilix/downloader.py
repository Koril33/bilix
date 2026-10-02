"""Bounded stream transfer with retries, backup URLs and byte-count verification."""

from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from .errors import NetworkError
from .models import Stream

ProgressCallback = Callable[[str, int, int | None], None]


def transfer(
    stream: Stream,
    target: Path,
    headers: dict[str, str],
    progress: ProgressCallback | None = None,
    attempts: int = 3,
) -> None:
    headers = {**headers, "Accept-Encoding": "identity"}
    if not stream.urls:
        raise NetworkError("没有可用的媒体流地址")
    for attempt in range(attempts):
        url = stream.urls[attempt % len(stream.urls)]
        try:
            with requests.Session() as session:
                with closing(
                    session.get(
                        url, headers=headers, stream=True, impersonate="chrome", timeout=(10, 300)
                    )
                ) as response:
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise NetworkError("服务器未返回完整媒体流")
                    length = response.headers.get("Content-Length")
                    expected = int(length) if length else stream.size
                    if expected is not None and expected <= 0:
                        raise NetworkError("服务器返回空媒体流")
                    completed = 0
                    if progress:
                        progress(target.stem, completed, expected)
                    with target.open("wb") as output:
                        for chunk in response.iter_content():
                            if not chunk:
                                continue
                            output.write(chunk)
                            completed += len(chunk)
                            if progress:
                                progress(target.stem, completed, expected)
                    if not completed or (expected is not None and completed != expected):
                        raise NetworkError("媒体流字节数不完整")
            return
        except (RequestException, NetworkError, ValueError):
            # Do not stringify third-party exceptions: they can include signed URLs/headers.
            if attempt + 1 == attempts:
                raise NetworkError(
                    f"{target.stem} 下载失败，已重试 {attempts} 次；服务器异常、连接中断或流不完整"
                ) from None
