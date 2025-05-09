import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Union, List
from urllib.parse import urlunsplit, urlsplit

import typer

from log_config import app_logger

def parse_page_input(value: Optional[str]) -> Union[str, List[int]]:
    """
    解析下载多 p 视频的传参
    """

    if value is None or value == "" or value == "all":
        return "all"
    elif '-' in value:
        try:
            start, end = map(int, value.split('-'))
            return list(range(start, end + 1))
        except Exception:
            raise typer.BadParameter("范围格式应为 起始-结束，例如 3-7")
    elif ',' in value:
        try:
            return [int(v.strip()) for v in value.split(',')]
        except Exception:
            raise typer.BadParameter("多个值应为英文逗号分隔，例如 1,4,9")
    else:
        try:
            return [int(value)]
        except Exception:
            raise typer.BadParameter("必须是整数、范围或英文逗号分隔的整数")


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """
    清理视频名称中的非法字符，使其可以安全作为文件名。

    参数:
        name: 原始视频标题。
        replacement: 用于替换非法字符的字符（默认下划线）。

    返回:
        清理后的字符串，可作为安全文件名使用。
    """
    # Windows 文件名非法字符: \ / : * ? " < > |，以及控制字符和空白尾随
    name = name.strip()  # 移除首尾空格
    name = name.replace("_哔哩哔哩_bilibili", "")
    name = re.sub(r'[\\/:*?"<>|]', replacement, name)  # 替换非法字符
    name = re.sub(r'[\x00-\x1f]', replacement, name)  # 控制字符
    name = re.sub(r'\s+', ' ', name)  # 连续空格变单空格
    name = name.strip(" .")  # 去除结尾的点和空格（Windows 不允许）
    name = name.replace("-电影-高清正版在线观看-bilibili-哔哩哔哩", "")
    name = name.replace("正片", "")
    name = name.replace(" ", replacement)
    # 限制长度（通常 255 是安全最大长度）
    return name[:240]  # 留一点空间给文件扩展名


def extract_playinfo_json(html_content: str):
    match = re.search(r'window\.__playinfo__\s*=\s*(\{.*?})\s*</script>', html_content, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            playinfo = json.loads(json_str)
            return playinfo
        except json.JSONDecodeError:
            app_logger.exception(f"解析 JSON 出错")
            return None
    else:
        app_logger.error("没有找到 window.__playinfo__ 的内容")
        return None


def extract_initial_state_json(html_content: str):
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?})\s*;', html_content, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            initial_state = json.loads(json_str)
            return initial_state
        except json.JSONDecodeError:
            app_logger.exception(f"解析 JSON 出错")
            return None
    else:
        app_logger.error("没有找到 window.__INITIAL_STATE__ 的内容")
        return None


def extract_title(html_content: str) -> str | None:
    match = re.search(r'<title\b[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        return sanitize_filename(title)
    return None


def extract_playurl_ssr_data(html_content: str) -> dict | None:
    pattern = r'const\s+playurlSSRData\s*=\s*({.*?})\s'
    match = re.search(pattern, html_content, re.DOTALL)

    if match:
        json_str = match.group(1)
        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
    return None



def merge_m4s_ffmpeg(video_file, audio_file, output_file):
    """
    使用 ffmpeg 合并视频和音频 m4s 文件到 mp4。

    Args:
        video_file (str): 视频 m4s 文件路径。
        audio_file (str): 音频 m4s 文件路径。
        output_file (str): 输出 mp4 文件路径。

    Returns:
        bool: True 如果合并成功，False 如果失败。
    """
    import sys, platform

    if not Path(video_file).exists():
        app_logger.error("无法找到 video m4s 文件")
        return None
    if not Path(audio_file).exists():
        app_logger.error("无法找到 audio m4s 文件")
        return None

    if platform.system() == 'Windows':
        if getattr(sys, "frozen", False):
            base_dir = os.path.dirname(__file__)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        ffmpeg_path = os.path.join(base_dir, 'ffmpeg.exe')
    else:
        ffmpeg_path = '/usr/bin/ffmpeg'

    command = [ffmpeg_path, '-i', video_file, '-i', audio_file, '-c', 'copy', output_file]

    try:
        # 执行命令并等待完成
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            app_logger.info(f"成功合并到: {output_file}")
            return True
        else:
            app_logger.error(f"合并失败，错误信息:\n{stderr.decode('utf-8')}")
            return False

    except FileNotFoundError:
        app_logger.exception("错误: ffmpeg 命令未找到，请确保已安装并添加到系统路径。")
        return False
    except Exception:
        app_logger.exception("未知错误")
        return False


def load_urls_from_file(file_path: str) -> list[str]:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    with path.open("r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    return urls


def clean_bili_url(url: str):
    parsed = urlsplit(url)
    clean_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return clean_url