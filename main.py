import asyncio
import json
import logging.config
import os.path
import re
import subprocess
import time
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Optional

import httpx
import typer
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn

from typer import Option

from log_config import log_config_dict

app = typer.Typer()
logging.config.dictConfig(log_config_dict)
app_logger = logging.getLogger('bilix')

headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0',
    'Cookie': "buvid3=3811CC7E-3BE1-947B-CC72-CEDB7A76FEFF35698infoc; b_nut=1724035335; _uuid=F8C1A6104-4788-DF43-4F11-BB2B65BC45CB36192infoc; buvid4=EAD0F3DB-F24E-D549-2229-54EFCF89D26637266-024081902-6GVRa3OrrpMoc68dd1U5zQ%3D%3D; bmg_af_switch=1; bmg_src_def_domain=i0.hdslb.com; header_theme_version=CLOSE; enable_web_push=DISABLE; rpdid=|(J|~)m~)YYu0J'u~kRukY~|J; buvid_fp_plain=undefined; hit-dyn-v2=1; DedeUserID=3305808; DedeUserID__ckMd5=7bb2e1b458a07561; enable_feed_channel=ENABLE; fingerprint=41616665b9dabc452ecc04afbe6067b2; buvid_fp=41616665b9dabc452ecc04afbe6067b2; share_source_origin=WEIXIN; CURRENT_QUALITY=0; home_feed_column=5; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NDU5NzQ1NzUsImlhdCI6MTc0NTcxNTMxNSwicGx0IjotMX0.eiidO8DseBfQKKXHZRmoh01E81kgBVjjNR9OZDoy1Dc; bili_ticket_expires=1745974515; bp_t_offset_3305808=1060368738949267456; SESSDATA=1e10c871%2C1761382965%2C7cfdb%2A41CjAxYrw-Q651dnlPn61AQwH7cLd_8bBDzpvKm1pkl305654xW-6hBjV9-Dv5oFGzCacSVm0xTUhHQkZZNERQS1BKSmVSb3NEaEh1N040TURYQVd6eExBQk5YR3EzbWNCdTV0b010SFRjal9XVk9NeWtpRGFVRmc0LTdyOFF2b3N6V0xxc2luaE1BIIEC; bili_jct=c81455f2096b7791f376fc144b85f8db; sid=7tsepjcu; b_lsid=CCDC86BE_1967F1170C6; bsource=search_bing; browser_resolution=1650-762; CURRENT_FNVAL=4048"
}


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


def extract_title(html_content: str) -> str | None:
    match = re.search(r'<title\b[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        return sanitize_filename(title)
    return None


async def parse_async(url: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url=url, headers=headers, timeout=5)
            response.raise_for_status()

            html = response.text
            # 标题和下载信息
            title = extract_title(html)
            playinfo = extract_playinfo_json(html)

            if playinfo:
                app_logger.info("成功提取到 playinfo JSON")
                playinfo['title'] = title
                return playinfo
            else:
                app_logger.error("未能提取到 playinfo JSON。")

        except httpx.RequestError:
            app_logger.exception(f'下载失败，网络请求错误')
        except httpx.HTTPStatusError:
            app_logger.exception(f'HTTP 错误')
        except Exception:
            app_logger.exception(f'未知错误')
    return None


async def download_stream_async(url: str, filename: str) -> None:
    """
    下载单个流（视频或音频）到本地文件
    """
    app_logger.info(f"开始下载: {filename}")
    async with httpx.AsyncClient(headers=headers, timeout=None) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        total = int(resp.headers.get('Content-Length', 0))
        app_logger.info(f'{filename} total size: {total} bytes')
        with open(filename, 'wb') as f:
            async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
    app_logger.info(f"{filename} 下载完成")


async def download_async(
        url: str,
        quality: Optional[int] = None
) -> None:
    """
    主逻辑：获取 playinfo，选择清晰度，下载视频和音频
    """
    playinfo = await parse_async(url)
    if not playinfo or 'data' not in playinfo:
        app_logger.error("无法获取播放信息，退出。")
        raise typer.Exit(code=1)

    dash = playinfo['data'].get('dash', {})
    videos = dash.get('video', [])
    audios = dash.get('audio', [])
    if not videos or not audios:
        app_logger.error("未检测到视频或音频流，退出。")
        raise typer.Exit(code=1)

    # 选择视频流
    if quality:
        selected = next((v for v in videos if v['id'] == quality), None)
        if not selected:
            app_logger.info(f"未找到清晰度 {quality}，使用最高质量。")
            selected = videos[0]
    else:
        selected = videos[0]

    video_url = selected.get('baseUrl') or selected.get('base_url')
    # 选择音频流（默认最高）
    audio = audios[0]
    audio_url = audio.get('baseUrl') or audio.get('base_url')

    # 下载
    title = playinfo['title']
    video_file = f'{title}_v_{selected["id"]}.m4s'
    audio_file = f'{title}_a_{selected["id"]}.m4s'
    output_file = f'{title}_{selected["id"]}.mp4'
    start = int(time.time() * 1000)
    # 同时下载视频和音频流
    await asyncio.gather(
        download_stream_async(video_url, video_file),
        download_stream_async(audio_url, audio_file)
    )
    end = int(time.time() * 1000)
    app_logger.info(f'下载音视频共耗时: {end - start} ms')

    if Path(output_file).exists():
        app_logger.warning('目标MP4存在，进行删除')
        Path.unlink(Path(output_file))

    app_logger.info("所有流下载完成，使用 ffmpeg 合并音视频")
    merge_m4s_ffmpeg(video_file, audio_file, output_file)
    Path.unlink(Path(video_file), missing_ok=True)
    Path.unlink(Path(audio_file), missing_ok=True)


def parse(url: str):
    with httpx.Client() as client:
        try:
            response = client.get(url=url, headers=headers, timeout=5)
            response.raise_for_status()

            html = response.text
            title = extract_title(html)
            playinfo = extract_playinfo_json(html)
            if playinfo:
                app_logger.info("成功提取到 playinfo JSON")
                playinfo['title'] = title
                return playinfo
            else:
                app_logger.error("未能提取到 playinfo JSON。")
        except httpx.RequestError:
            app_logger.exception(f'下载失败，网络请求错误')
        except httpx.HTTPStatusError:
            app_logger.exception(f'HTTP 错误')
        except Exception:
            app_logger.exception(f'未知错误')
    return None


def download_stream(url: str, filename: str):
    app_logger.info(f"开始下载: {filename}")

    with httpx.Client(headers=headers, timeout=None) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('Content-Length', 0))
            app_logger.info(f'{filename} total size: {total} bytes')
            with Progress(
                    TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                    TimeRemainingColumn(),
            ) as progress:
                task_id = progress.add_task(f"download-{filename}", filename=filename, total=total)
                with open(filename, 'wb') as f:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                        progress.update(task_id, advance=len(chunk))

    app_logger.info(f"{filename} 下载完成")


def download_sync(
        url: str,
        quality: Optional[int] = None
):
    playinfo = parse(url)
    if not playinfo or 'data' not in playinfo:
        app_logger.error("无法获取播放信息，退出。")
        raise typer.Exit(code=1)

    dash = playinfo['data'].get('dash', {})
    videos = dash.get('video', [])
    audios = dash.get('audio', [])
    if not videos or not audios:
        app_logger.error("未检测到视频或音频流，退出。")
        raise typer.Exit(code=1)

    # 选择视频流
    if quality:
        selected = next((v for v in videos if v['id'] == quality), None)
        if not selected:
            app_logger.info(f"未找到清晰度 {quality}，使用最高质量。")
            selected = videos[0]
    else:
        selected = videos[0]

    video_url = selected.get('baseUrl') or selected.get('base_url')
    # 选择音频流（默认最高）
    audio = audios[0]
    audio_url = audio.get('baseUrl') or audio.get('base_url')

    # 下载
    title = playinfo['title']
    video_file = f'{title}_v_{selected["id"]}.m4s'
    audio_file = f'{title}_a_{selected["id"]}.m4s'
    output_file = f'{title}_{selected["id"]}.mp4'
    start = int(time.time() * 1000)

    download_stream(video_url, video_file)
    download_stream(audio_url, audio_file)

    end = int(time.time() * 1000)
    app_logger.info(f'下载音视频共耗时: {end - start} ms')

    if Path(output_file).exists():
        app_logger.warning('目标MP4存在，进行删除')
        Path.unlink(Path(output_file))

    app_logger.info("所有流下载完成，使用 ffmpeg 合并音视频")
    merge_m4s_ffmpeg(video_file, audio_file, output_file)
    Path.unlink(Path(video_file), missing_ok=True)
    Path.unlink(Path(audio_file), missing_ok=True)


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


@app.command()
def download(
        url: Annotated[str, typer.Argument(help="目标视频 URL")],
        quality: Optional[int] = Option(None, "--quality", help="视频清晰度"),
) -> None:
    """
    下载 Bilibili 视频及音频流，并提供清晰度选择。
    """
    start = int(time.time() * 1000)
    try:
        headers['Referer'] = url
        # asyncio.run(download_async(url, quality))
        download_sync(url, quality)
    except Exception:
        app_logger.exception(f"下载过程中出现错误")
        raise typer.Exit(code=1)
    finally:
        end = int(time.time() * 1000)

        app_logger.info(f'总耗时: {end - start} ms')


if __name__ == '__main__':
    app()
