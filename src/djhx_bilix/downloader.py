"""Bounded stream transfer with retries, backup URLs and byte-count verification."""

import re
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from curl_cffi.requests.exceptions import RequestException

from .errors import NetworkError
from .feedback import TransferSample
from .models import Stream
from .network import session as request_session
from .operations import CancellationToken

ProgressCallback = Callable[[str, int, int | None], None]


class _Paused(Exception):
    pass


def transfer(
    stream: Stream,
    target: Path,
    headers: dict[str, str],
    progress: ProgressCallback | None = None,
    attempts: int = 3,
    *,
    cancel: CancellationToken | None = None,
    feedback: Callable[[TransferSample], None] | None = None,
    proxy: str | None = None,
    refresh: Callable[[], Stream] | None = None,
) -> None:
    if cancel:
        cancel.raise_if_cancelled()
    headers = {**headers, "Accept-Encoding": "identity"}
    if not stream.urls:
        raise NetworkError("没有可用的媒体流地址")
    stream_attempt = 0
    for attempt in range(attempts):
        stream_attempt += 1
        completed, expected, sequence = 0, None, 0
        validator = None

        def report(phase):
            nonlocal sequence
            sequence += 1
            if feedback:
                feedback(
                    TransferSample(
                        target.stem,
                        stream_attempt,
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
            while True:
                if cancel:
                    cancel.checkpoint()
                offset = completed if validator else 0
                request_headers = dict(headers)
                if offset:
                    request_headers.update(Range=f"bytes={offset}-", **{"If-Range": validator})
                try:
                    with request_session(proxy=proxy) as session:
                        response = session.get(
                            url,
                            headers=request_headers,
                            stream=True,
                            impersonate="chrome",
                            timeout=(10, 15 if cancel else 300),
                        )
                        with closing(response):
                            if cancel:
                                cancel.raise_if_cancelled()
                            if response.status_code in {401, 403, 410} and refresh:
                                stream = refresh()
                                url = stream.urls[0]
                                raise NetworkError("媒体地址已更新，将重新连接")
                            response.raise_for_status()
                            previous_total = expected
                            etag = response.headers.get("ETag")
                            fresh_validator = (
                                etag
                                if etag and not etag.startswith("W/")
                                else response.headers.get("Last-Modified")
                            )
                            if offset and response.status_code == 206:
                                match = re.fullmatch(
                                    r"bytes (\d+)-(\d+)/(\d+)",
                                    response.headers.get("Content-Range", ""),
                                )
                                if (
                                    not match
                                    or int(match[1]) != offset
                                    or fresh_validator != validator
                                ):
                                    raise NetworkError("续传响应不匹配，拒绝拼接媒体")
                                expected = int(match[3])
                                if int(match[2]) != expected - 1 or expected <= offset:
                                    raise NetworkError("续传范围不完整")
                                length = response.headers.get("Content-Length")
                                if length and int(length) != expected - offset:
                                    raise NetworkError("续传字节长度不匹配")
                                if previous_total is not None and expected != previous_total:
                                    raise NetworkError("媒体资源大小已变化")
                            elif response.status_code == 200:
                                # Ignored Range or changed resource: replace partial data safely.
                                completed = offset = 0
                                length = response.headers.get("Content-Length")
                                expected = int(length) if length else stream.size
                            else:
                                raise NetworkError("服务器未返回完整媒体流")
                            validator = fresh_validator
                            if expected is not None and expected <= 0:
                                raise NetworkError("服务器返回空媒体流")
                            report("receiving")
                            if progress:
                                progress(target.stem, completed, expected)
                            with target.open("ab" if offset else "wb") as output:
                                for chunk in response.iter_content():
                                    if cancel:
                                        cancel.raise_if_cancelled()
                                        if getattr(cancel, "paused", False):
                                            raise _Paused
                                    if not chunk:
                                        continue
                                    output.write(chunk)
                                    completed += len(chunk)
                                    report("receiving")
                                    if progress:
                                        progress(target.stem, completed, expected)
                                    if cancel and getattr(cancel, "paused", False):
                                        raise _Paused
                            if cancel:
                                cancel.raise_if_cancelled()
                            if not completed or (expected is not None and completed != expected):
                                raise NetworkError("媒体流字节数不完整")
                            report("finished")
                            return
                except _Paused:
                    report("paused")
                    cancel.checkpoint()
                    if expected is not None and completed == expected:
                        report("finished")
                        return
                    # A new stream attempt clears speed samples, retaining only verified offset.
                    sequence = 0
                    stream_attempt += 1
                    report("connecting")
                    continue
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
