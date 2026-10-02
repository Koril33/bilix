"""Network boundary. Exceptions contain no request headers or server response bodies."""

from dataclasses import replace
from urllib.parse import urlsplit

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from ..config import Settings
from ..credentials import normalize_cookie
from ..errors import APIError, BilixError, NetworkError
from ..models import Page, VideoInfo
from ..urls import normalize_url
from .parser import apply_playback, parse_video

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136.0.0.0 Safari/537.36"
)


def cookie_header(settings: Settings) -> str:
    if not settings.token_file.is_file():
        return ""
    try:
        cookie = settings.token_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise BilixError("无法读取登录凭据，请重新执行 blx auth login") from None
    return normalize_cookie(cookie, require_session=True)


class BilibiliClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def headers(self, referer: str = "https://www.bilibili.com/") -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Referer": referer}
        cookie = cookie_header(self.settings)
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def resolve(self, url: str) -> str:
        url = normalize_url(url)
        if urlsplit(url).hostname != "b23.tv":
            return url
        try:
            # A short-link request never receives the user's Bilibili credentials.
            with requests.Session() as session:
                response = session.get(url, timeout=15, headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                target = normalize_url(response.url)
        except RequestException:
            raise NetworkError("短链接解析失败，请稍后重试或使用完整视频地址") from None
        if urlsplit(target).hostname != "www.bilibili.com":
            raise BilixError("短链接未指向支持的 Bilibili 视频")
        return target

    def fetch(self, url: str) -> VideoInfo:
        url = self.resolve(url)
        try:
            with requests.Session() as session:
                response = session.get(url, headers=self.headers(url), timeout=20)
                response.raise_for_status()
                info = parse_video(response.text, url)
            if info.episode_id and not info.videos:
                # SSR occasionally omits video_info even for an authorized account.
                # Use the capabilities advertised by the official web player.
                playback = self.api(
                    "pgc/player/web/v2/playurl",
                    {"ep_id": info.episode_id, "qn": 127, "fnval": 143312, "fourk": 1},
                )
                info = apply_playback(info, playback)
            if "/bangumi/media/" in url or "/bangumi/play/ss" in url:
                pages = self.episodes(url)
                primary_matches = info.cid and any(page.cid == info.cid for page in pages)
                permissions_known = info.videos or info.is_preview or info.is_drm
                if not primary_matches or not permissions_known:
                    # Season/media landing pages can expose a promotional trailer,
                    # whose free streams do not describe the main episodes' rights.
                    # Matching metadata alone also cannot establish playback access.
                    primary = self.fetch(pages[0].url)
                    info = replace(primary, url=url, season_id=primary.season_id or info.season_id)
                info = replace(info, pages=pages)
        except RequestException:
            raise NetworkError("获取视频页面失败，请检查网络后重试") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise BilixError("视频页面数据不完整或格式已变化") from None
        return info

    def api(self, path: str, params: dict | None = None, *, passport: bool = False) -> dict:
        host = "passport.bilibili.com" if passport else "api.bilibili.com"
        try:
            with requests.Session() as session:
                response = session.get(
                    f"https://{host}/{path}", params=params, headers=self.headers(), timeout=15
                )
                response.raise_for_status()
                value = response.json()
        except (RequestException, ValueError):
            raise NetworkError("Bilibili 接口请求失败，请稍后重试") from None
        if not isinstance(value, dict) or type(value.get("code")) is not int:
            raise BilixError("Bilibili 接口响应格式错误")
        if value["code"] != 0:
            raise APIError(value["code"])
        if any(
            value.get(key) is not None and not isinstance(value[key], dict)
            for key in ("data", "result")
        ):
            raise BilixError("Bilibili 接口响应格式错误")
        return value.get("data") or value.get("result") or {}

    def episodes(self, url: str) -> tuple[Page, ...]:
        identifier = urlsplit(url).path.split("/")[-1]
        if identifier.startswith("md"):
            media = self.api("pgc/review/user", {"media_id": identifier[2:]})
            season_id = media.get("media", {}).get("season_id")
        else:
            season_id = identifier[2:]
        if not season_id:
            raise BilixError("未能获取番剧的 season_id")
        section = self.api("pgc/web/season/section", {"season_id": season_id})
        episodes = section.get("main_section", {}).get("episodes", [])
        if not episodes:
            raise BilixError("该番剧暂无可用选集")
        return tuple(
            Page(
                i,
                f"{e.get('title', i)} {e.get('long_title', '')}".strip(),
                normalize_url(
                    e.get("share_url") or f"https://www.bilibili.com/bangumi/play/ep{e['id']}"
                ),
                float(e.get("duration", 0)) / 1000,
                str(e.get("cid", "")),
            )
            for i, e in enumerate(episodes, 1)
        )
