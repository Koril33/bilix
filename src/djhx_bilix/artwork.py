"""Bounded, credential-free cover downloads shared by the CLI and desktop."""

from urllib.parse import urlsplit

from curl_cffi.requests.exceptions import RequestException

from .errors import NetworkError
from .network import session


def cover_url(url: str) -> str:
    url = "https:" + url if url.startswith("//") else url
    try:
        parsed = urlsplit(url)
        allowed = any(
            parsed.hostname == domain or (parsed.hostname or "").endswith("." + domain)
            for domain in ("hdslb.com", "bilibili.com")
        )
        if (
            parsed.scheme not in {"http", "https"}
            or not allowed
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 80 if parsed.scheme == "http" else 443)
        ):
            raise ValueError
        return parsed._replace(scheme="https", netloc=parsed.hostname).geturl()
    except ValueError:
        raise NetworkError("封面地址缺失或不受支持") from None


def image_extension(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff") and data.rstrip().endswith(b"\xff\xd9"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82"):
        return ".png"
    if data[:6] in {b"GIF87a", b"GIF89a"} and data.endswith(b";"):
        return ".gif"
    if (
        data[:4] == b"RIFF"
        and data[8:12] == b"WEBP"
        and int.from_bytes(data[4:8], "little") + 8 == len(data)
    ):
        return ".webp"
    raise NetworkError("封面响应不是完整的受支持图片")


def download_cover(url: str, *, cancel=None, proxy=None) -> tuple[bytes, str]:
    url = cover_url(url)
    try:
        if cancel:
            cancel.checkpoint()
        with session(proxy=proxy) as connection:
            response = connection.get(url, timeout=(10, 20), stream=True, allow_redirects=False)
            try:
                if response.status_code != 200:
                    raise NetworkError("封面获取失败，请稍后重试")
                data = bytearray()
                for chunk in response.iter_content():
                    if cancel:
                        cancel.checkpoint()
                    data.extend(chunk)
                    if len(data) > 20 * 1024 * 1024:
                        raise NetworkError("封面超过 20 MiB，未保存")
                value = bytes(data)
                return value, image_extension(value)
            finally:
                response.close()
    except RequestException:
        if cancel:
            cancel.raise_if_cancelled()
        raise NetworkError("封面下载连接失败，请稍后重试") from None
