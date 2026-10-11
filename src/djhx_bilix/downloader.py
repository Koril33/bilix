"""Bounded stream transfer with retries, backup URLs and byte-count verification."""

import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from .errors import NetworkError
from .feedback import TransferSample
from .models import Stream
from .operations import CancellationToken

ProgressCallback = Callable[[str, int, int | None], None]


def transfer(
    stream: Stream,
    target: Path,
    headers: dict[str, str],
    progress: ProgressCallback | None = None,
    attempts: int = 3,
    *,
    cancel: CancellationToken | None = None,
    feedback: Callable[[TransferSample], None] | None = None,
) -> None:
    if cancel:
        cancel.raise_if_cancelled()
    headers = {**headers, "Accept-Encoding": "identity"}
    if not stream.urls:
        raise NetworkError("没有可用的媒体流地址")
    for attempt in range(attempts):
        completed, expected, sequence = 0, None, 0

        def report(phase):
            nonlocal sequence
            sequence += 1
            if feedback:
                feedback(
                    TransferSample(
                        target.stem,
                        attempt + 1,
                        sequence,
                        phase,
                        completed,
                        expected,
                        time.monotonic(),
                    )
                )

        if cancel:
            cancel.raise_if_cancelled()
        report("connecting")
        url = stream.urls[attempt % len(stream.urls)]
        try:
            with requests.Session() as session:
                with closing(
                    session.get(
                        url,
                        headers=headers,
                        stream=True,
                        impersonate="chrome",
                        timeout=(10, 15 if cancel else 300),
                    )
                ) as response:
                    if cancel:
                        cancel.raise_if_cancelled()
                    response.raise_for_status()
                    if response.status_code != 200:
                        raise NetworkError("服务器未返回完整媒体流")
                    length = response.headers.get("Content-Length")
                    expected = int(length) if length else stream.size
                    if expected is not None and expected <= 0:
                        raise NetworkError("服务器返回空媒体流")
                    completed = 0
                    report("receiving")
                    if progress:
                        progress(target.stem, completed, expected)
                    with target.open("wb") as output:
                        for chunk in response.iter_content():
                            if cancel:
                                cancel.raise_if_cancelled()
                            if not chunk:
                                continue
                            output.write(chunk)
                            completed += len(chunk)
                            report("receiving")
                            if progress:
                                progress(target.stem, completed, expected)
                    if cancel:
                        cancel.raise_if_cancelled()
                    if not completed or (expected is not None and completed != expected):
                        raise NetworkError("媒体流字节数不完整")
                    report("finished")
            return
        except (RequestException, NetworkError, ValueError):
            if cancel:
                cancel.raise_if_cancelled()
            # Do not stringify third-party exceptions: they can include signed URLs/headers.
            if attempt + 1 == attempts:
                report("failed")
                raise NetworkError(
                    f"{target.stem} 下载失败，已重试 {attempts} 次；服务器异常、连接中断或流不完整"
                ) from None
            report("retrying")
