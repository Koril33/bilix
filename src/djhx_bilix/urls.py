"""URL normalization and explicit, bounded page selection."""

import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .errors import InputError


def normalize_url(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", value):
        value = f"https://www.bilibili.com/video/{value}"
    try:
        parts = urlsplit(value)
        if parts.port not in (None, 443, 80) or parts.username or parts.password:
            raise ValueError
    except ValueError:
        raise InputError("视频 URL 格式错误") from None
    if parts.scheme not in ("http", "https"):
        raise InputError("请使用 Bilibili 视频 URL 或 BV 号")
    if parts.hostname in ("b23.tv", "www.b23.tv"):
        if not re.fullmatch(r"/[0-9A-Za-z]+/?", parts.path):
            raise InputError("b23.tv 短链接格式错误")
        return urlunsplit(("https", "b23.tv", parts.path.rstrip("/"), "", ""))
    if parts.hostname not in ("bilibili.com", "www.bilibili.com"):
        raise InputError("仅支持 bilibili.com 视频和 b23.tv 短链接")
    path = parts.path.rstrip("/")
    if not re.fullmatch(
        r"/(?:video/(?:BV[0-9A-Za-z]{10}|av\d+)|"
        r"bangumi/play/(?:ep\d+|ss\d+)|bangumi/media/md\d+)",
        path,
    ):
        raise InputError("不支持该地址，请提供 BV/av 视频或 ep/ss/md 番剧链接")
    query = parse_qs(parts.query, keep_blank_values=True)
    if "p" in query:
        if len(query["p"]) != 1 or not query["p"][0].isdigit() or int(query["p"][0]) < 1:
            raise InputError("链接中的 p 必须是正整数")
        page_query = urlencode({"p": int(query["p"][0])})
    else:
        page_query = ""
    return urlunsplit(("https", "www.bilibili.com", path, page_query, ""))


def url_page(url: str) -> int | None:
    query = parse_qs(urlsplit(url).query)
    return int(query["p"][0]) if "p" in query else None


def with_page(url: str, number: int) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode({"p": number}), ""))


def parse_pages(value: str | None) -> tuple[int, ...] | None:
    """None means all pages. Reject duplicates and reversed/oversized ranges."""
    if value is None or value.lower().strip() == "all":
        return None
    selected = []
    for segment in value.split(","):
        segment = segment.strip()
        match = re.fullmatch(r"([1-9]\d*)(?:-([1-9]\d*))?", segment)
        if not match:
            raise InputError("--page 应为正整数、1,3,5-7 或 all")
        start, end = int(match[1]), int(match[2] or match[1])
        if start > end or end > 10000:
            raise InputError("--page 范围必须递增，且不能超过 10000")
        selected.extend(range(start, end + 1))
        if len(selected) > 10000:
            raise InputError("选集数量不能超过 10000")
    if len(selected) != len(set(selected)):
        raise InputError("--page 包含重复集数")
    return tuple(selected)


def load_urls(path: Path) -> list[str]:
    try:
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except (OSError, UnicodeError):
        raise InputError("无法读取 URL 文件，请使用 UTF-8 文本，每行一个链接") from None
