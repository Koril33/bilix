"""Explicit proxy selection shared by account, media, artwork and update requests."""

from urllib.parse import urlsplit

from curl_cffi import requests

from .errors import InputError


def validate_proxy(value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise InputError("代理地址必须为字符串")
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        raise InputError("代理主机或端口无效") from None
    if parsed.scheme not in {"http", "https", "socks5", "socks5h"} or not hostname:
        raise InputError("代理地址须使用 http、https、socks5 或 socks5h，并填写主机")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise InputError("代理地址不能包含路径、查询或片段")
    return value


def session(*, proxy: str | None = None, **kwargs):
    # Explicit config wins; otherwise curl_cffi retains its normal environment rules.
    if proxy is None:
        from .config import load_settings

        proxy = load_settings().proxy
    return requests.Session(**kwargs, **({"proxy": proxy} if proxy else {}))
