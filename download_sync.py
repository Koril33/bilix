
import time
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import httpx
import typer
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn, \
    MofNCompleteColumn, FileSizeColumn, TotalFileSizeColumn, SpinnerColumn

from log_config import app_logger
from tool import extract_title, extract_playinfo_json, merge_m4s_ffmpeg

def parse(url: str, headers: dict):
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


def download_stream(url: str, headers, filename: str, progress):
    task = progress.add_task(f'{filename}', start=False)
    with httpx.Client().stream("GET", url=url, headers=headers) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get('Content-Length', 0))
        progress.update(task, total=total)
        progress.start_task(task)
        with open(filename, 'wb') as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
                progress.update(task, advance=len(chunk))


def download_stream_requests(url, headers, filename, progress):
    import requests
    task = progress.add_task(f'{filename}', start=False)
    with requests.get(url, headers=headers, stream=True) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get('Content-Length', 0))
        progress.update(task, total=total)
        progress.start_task(task)
        with open(filename, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                progress.update(task, advance=len(chunk))


def download_sync(
        url: str,
        headers: dict,
        quality: Optional[int] = None
):
    playinfo = parse(url, headers)
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

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        MofNCompleteColumn(),
        FileSizeColumn(),
        TotalFileSizeColumn(),
        SpinnerColumn(),
    ) as progress:
        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.submit(download_stream, video_url, headers, video_file, progress)
            executor.submit(download_stream, audio_url, headers, audio_file, progress)


    end = int(time.time() * 1000)
    app_logger.info(f'下载音视频共耗时: {end - start} ms')

    if Path(output_file).exists():
        app_logger.warning('目标MP4存在，进行删除')
        Path.unlink(Path(output_file))

    app_logger.info("所有流下载完成，使用 ffmpeg 合并音视频")
    merge_m4s_ffmpeg(video_file, audio_file, output_file)
    Path.unlink(Path(video_file), missing_ok=True)
    Path.unlink(Path(audio_file), missing_ok=True)