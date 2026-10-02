"""Decode embedded JSON using a JSON decoder, not a brace-matching regex."""

import html
import json
import re
from dataclasses import replace
from urllib.parse import urlsplit

from ..errors import BilixError
from ..models import Page, Stream, VideoInfo
from ..urls import with_page


def embedded_json(document: str, name: str) -> dict:
    match = re.search(r"\b(?:window\.)?" + re.escape(name) + r"\s*=\s*", document)
    if not match:
        return {}
    expression = document[match.end() :].lstrip()
    # PGC pages assign window.__playinfo__ = playurlSSRData.data. Never evaluate JS.
    if re.match(
        r"playurlSSRData(?:\.(?:data|result|raw))+[ \t]*(?:;|\r?\n|</script>|$)", expression
    ):
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(expression)
    except ValueError:
        raise BilixError("页面内的播放数据格式错误") from None
    return value if isinstance(value, dict) else {}


def next_season(document: str) -> dict:
    match = re.search(
        r'<script\b(?=[^>]*\bid=["\']__NEXT_DATA__["\'])[^>]*>(.*?)</script>', document, re.S
    )
    if not match:
        return {}
    try:
        props = json.loads(match[1]).get("props", {}).get("pageProps", {})
    except (ValueError, AttributeError):
        raise BilixError("影视页面元数据格式错误") from None
    for query in (props.get("dehydratedState") or {}).get("queries", []):
        data = (query.get("state") or {}).get("data") or {}
        if isinstance(data, dict) and data.get("season_id") and data.get("title"):
            return data
    return {}


def _stream(raw: dict, audio_kind: str = "aac") -> Stream | None:
    base = raw.get("baseUrl") or raw.get("base_url")
    backups = raw.get("backupUrl") or raw.get("backup_url") or []
    if isinstance(backups, str):
        backups = [backups]
    urls = tuple(dict.fromkeys(u for u in [base, *backups] if isinstance(u, str)))
    if not urls:
        return None
    return Stream(
        int(raw.get("id", 0)),
        int(raw.get("codecid", 0)),
        int(raw.get("bandwidth", 0)),
        urls,
        int(raw["size"]) if raw.get("size") else None,
        audio_kind,
    )


def apply_playback(info: VideoInfo, data: dict) -> VideoInfo:
    """Normalize page/API playback shapes through one stream adapter."""
    play = data.get("video_info") or data
    dash = play.get("dash") or {}
    videos = tuple(s for v in dash.get("video", []) if (s := _stream(v)))
    audios = [s for a in dash.get("audio", []) if (s := _stream(a))]
    dolby = (dash.get("dolby") or {}).get("audio") or []
    if isinstance(dolby, dict):
        dolby = [dolby]
    audios.extend(s for a in dolby if (s := _stream(a, "dolby")))
    flac = (dash.get("flac") or {}).get("audio")
    if isinstance(flac, dict) and (stream := _stream(flac, "flac")):
        audios.append(stream)
    duration = float(play.get("timelength") or 0) / 1000 or info.duration
    return replace(
        info,
        duration=duration,
        videos=videos,
        audios=tuple(audios),
        bvid=str((data.get("arc") or {}).get("bvid") or info.bvid),
        cid=str((data.get("arc") or {}).get("cid") or info.cid),
        advertised_qualities=tuple(play.get("accept_quality") or []),
        is_preview=bool(play.get("is_preview")),
        is_drm=bool(play.get("is_drm")),
    )


def parse_video(document: str, url: str) -> VideoInfo:
    state = embedded_json(document, "__INITIAL_STATE__")
    play = embedded_json(document, "__playinfo__").get("data") or {}
    ssr = embedded_json(document, "playurlSSRData")
    ssr_data = ssr.get("data") or ssr
    result = ssr_data.get("result") or {}
    raw = (ssr_data.get("raw") or {}).get("data") or {}
    if result or raw:
        play = result.get("video_info") or raw.get("video_info") or play
    episode = (result.get("play_view_business_info") or {}).get("episode_info") or {}
    supplement = result.get("supplement") or {}
    episode_meta = supplement.get("ogv_episode_info") or {}
    arc = result.get("arc") or raw.get("arc") or {}
    video = state.get("videoData") or {}
    media = state.get("mediaInfo") or next_season(document)
    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", document, re.I | re.S)
    title = (
        video.get("title")
        or media.get("title")
        or (html.unescape(title_match[1].strip()) if title_match else "")
    )
    title = re.sub(r"_哔哩哔哩_bilibili$", "", title)
    episode_title = episode_meta.get("long_title") or ""
    if episode_title:
        title += " · " + episode_title
    if not title or not (state or play or result or raw or media):
        raise BilixError("未找到视频数据：链接可能无效、视频已删除，或需要登录后访问")
    pages = tuple(
        Page(
            int(p["page"]),
            p.get("part", ""),
            with_page(url, int(p["page"])),
            float(p.get("duration", 0)),
            str(p.get("cid", "")),
        )
        for p in video.get("pages", [])
    )
    bvid = state.get("bvid") or video.get("bvid") or episode.get("bvid") or arc.get("bvid")
    cid = state.get("cid") or episode.get("cid") or arc.get("cid")
    if not bvid and urlsplit(url).path.startswith("/video/BV"):
        bvid = urlsplit(url).path.split("/")[-1]
    current = next((p for p in pages if p.cid == str(cid)), None)
    duration = float(play.get("timelength", 0)) / 1000 or (current.duration if current else 0)
    info = VideoInfo(
        url,
        title,
        str(bvid or ""),
        str(cid or ""),
        duration,
        pages,
        description=video.get("desc") or media.get("evaluate", ""),
        owner=(video.get("owner") or {}).get("name", ""),
        episode_id=str(
            episode.get("ep_id")
            or episode_meta.get("episode_id")
            or (
                urlsplit(url).path.rsplit("/", 1)[-1][2:]
                if re.search(r"/bangumi/play/ep\d+$", urlsplit(url).path)
                else ""
            )
        ),
        season_id=str(
            media.get("season_id")
            or (result.get("play_view_business_info") or {}).get("season_info", {}).get("season_id")
            or ""
        ),
    )
    return apply_playback(info, play)
