"""Portable output names with room for identifiers, quality and extensions."""

import html
import re
from string import Formatter

from .errors import InputError

TEMPLATE_FIELDS = frozenset({"title", "owner", "part", "page", "bvid", "cid", "quality", "codec"})


def validate_template(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 300:
        raise InputError("命名模板须为 1 到 300 个字符")
    try:
        for _, field, spec, conversion in Formatter().parse(value):
            if field is not None and (field not in TEMPLATE_FIELDS or spec or conversion):
                raise ValueError
    except ValueError:
        raise InputError(
            "命名模板仅支持 title、owner、part、page、bvid、cid、quality、codec 字段"
        ) from None


def render_template(template: str, **values: str) -> str:
    validate_template(template)
    return safe_filename(template.format_map(values))


def safe_filename(name: str, limit: int = 110) -> str:
    name = html.unescape(name)
    name = re.sub(r"(?:_哔哩哔哩_bilibili|[-_]bilibili[-_]哔哩哔哩)$", "", name)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")[:limit].rstrip(" .") or "video"
    if re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I):
        name = "_" + name
    # Most Linux filesystems limit names by bytes; UTF-8 Chinese takes 3 bytes.
    return name.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .")
