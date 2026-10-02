"""Portable output names with room for identifiers, quality and extensions."""

import html
import re


def safe_filename(name: str, limit: int = 110) -> str:
    name = html.unescape(name)
    name = re.sub(r"(?:_哔哩哔哩_bilibili|[-_]bilibili[-_]哔哩哔哩)$", "", name)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")[:limit].rstrip(" .") or "video"
    if re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I):
        name = "_" + name
    # Most Linux filesystems limit names by bytes; UTF-8 Chinese takes 3 bytes.
    return name.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .")
