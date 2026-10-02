"""Cookie normalization, including token files written by pre-1.4 clients."""

import re
from http.cookies import CookieError, SimpleCookie

from .errors import BilixError


def normalize_cookie(value: str, *, require_session: bool = False) -> str:
    if "\r" in value or "\n" in value:
        raise BilixError("登录凭据格式错误，请重新执行 blx auth login")
    value = value.strip()
    if not value:
        if require_session:
            raise BilixError("登录凭据为空，请重新执行 blx auth login")
        return ""
    # Old versions stored multiple Set-Cookie headers as one comma-separated string.
    # Keep Expires' internal comma; split only before the next cookie name=value.
    segments = re.split(r",\s*(?=[A-Za-z0-9_]+=[^;]*)", value)
    cookies = {}
    try:
        for segment in segments:
            parsed = SimpleCookie()
            parsed.load(segment)
            cookies.update({key: morsel.coded_value for key, morsel in parsed.items()})
    except CookieError:
        raise BilixError("登录凭据格式错误，请重新执行 blx auth login") from None
    if not cookies or (require_session and not cookies.get("SESSDATA")):
        raise BilixError("登录凭据缺少有效的 SESSDATA，请重新执行 blx auth login")
    return "; ".join(f"{key}={value}" for key, value in cookies.items())
