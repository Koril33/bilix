import math
import time
from collections import OrderedDict, defaultdict
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import httpx
import typer
from curl_cffi import requests
from curl_cffi.requests.exceptions import HTTPError, RequestException
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn, \
    MofNCompleteColumn, FileSizeColumn, TotalFileSizeColumn, SpinnerColumn
from rich.text import Text

from log_config import app_logger
from tool import extract_title, extract_playinfo_json, merge_m4s_ffmpeg, extract_initial_state_json, \
    extract_playurl_ssr_data, format_bytes, shrink_title

# B 站视频编码
codec_dict = {
    7: 'AVC(H.264)',
    12: 'HEVC(H.265)',
    13: 'AV1',
}

codec_name_id_map = {
    'AVC': 7,
    'HEVC': 12,
    'AV1': 13
}

quality_id_name_map = {
    6: '240P',
    16: '360P',
    32: '480P',
    64: '720P',
    74: '720P60',
    80: '1080P',
    112: '1080P+',
    116: '1080P60',
    120: '4K',
    125: 'HDR',
    126: '杜比视界',
    127: '8K'
}


def get_video_info(url: str, header: dict):
    parse_res = parse(url, header)
    console = Console()

    video_url = url
    video_title = parse_res['title']
    if parse_res.get('playurl_ssr_data'):
        result = parse_res.get('playurl_ssr_data').get('result')
        raw = parse_res.get('playurl_ssr_data').get('raw')

        if result:
            video_info = result.get('video_info')
            episode_info = result.get('play_view_business_info').get('episode_info')
            aid = episode_info.get('aid')
            bvid = episode_info.get('bvid')
            cid = episode_info.get('cid')
        elif raw:
            video_info = raw.get('data').get('video_info')
            arc = raw.get('data').get('arc')
            aid = arc.get('aid')
            bvid = arc.get('bvid')
            cid = arc.get('cid')
        else:
            app_logger.error(f"无法获取该 URL : {url} 的 video_info")
            raise typer.Exit(code=1)

        codecid_dict = defaultdict(list)
        if video_info.get('dash'):
            dash_video = video_info['dash']['video']

            for v in dash_video:
                codecid_dict[v['id']].append(codec_dict.get(v['codecid']) + '-' + format_bytes(v['size']))

        accept_quality = video_info['accept_quality']
        accept_description = video_info['accept_description']

        timelength = video_info['timelength']
        video_format = video_info['format']

    elif parse_res.get('playinfo'):
        data = parse_res.get('playinfo').get('data')
        accept_quality = data['accept_quality']
        accept_description = data['accept_description']
        timelength = data['timelength']
        video_format = data['format']

        dash_video = data['dash']['video']
        codecid_dict = defaultdict(list)
        for v in dash_video:
            # video_size = format_bytes(estimate_size(v['bandwidth'], timelength // 1000))
            # video_size = format_bytes(get_url_size(v['baseUrl'], header))
            codecid_dict[v['id']].append(codec_dict.get(v['codecid']))
    else:
        app_logger.error("无法找到视频信息")
        return

    if parse_res.get('initial_state'):
        aid = parse_res.get('initial_state').get('aid')
        bvid = parse_res.get('initial_state').get('bvid')
        cid = parse_res.get('initial_state').get('cid')

    qualities = OrderedDict(zip(accept_quality, accept_description))

    # 视频时长毫秒转分钟秒的字符串格式
    total_seconds = math.ceil(timelength / 1000)
    minutes, seconds = divmod(total_seconds, 60)

    # 构造内容
    text = Text()
    text.append("视频 URL：", style="bold cyan")
    text.append(video_url + "\n", style="bold green")
    text.append("视频标题：", style="bold cyan")
    text.append(video_title + "\n", style="bold magenta")
    text.append("视频格式：", style="bold cyan")
    text.append(str(video_format) + "\n", style="bold magenta")
    text.append("aid：", style="bold cyan")
    text.append(str(aid) + "\n", style="bold magenta")
    text.append("bvid：", style="bold cyan")
    text.append(str(bvid) + "\n", style="bold magenta")
    text.append("cid：", style="bold cyan")
    text.append(str(cid) + "\n", style="bold magenta")
    text.append("视频时长：", style="bold cyan")
    text.append(f'{minutes} 分 {seconds} 秒' + "\n\n", style="bold magenta")

    text.append("可选择清晰度：\n", style="bold yellow")

    for key, value in qualities.items():
        text.append(f"{key} - {value} - 支持编码: {codecid_dict.get(key)}\n", style="bold white")

    if parse_res.get('initial_state'):
        pages_info = parse_res.get('initial_state').get('videoData').get('pages')
        text.append("\n选集信息：\n", style="bold yellow")
        for page in pages_info:
            # 转换时长格式（秒 -> 分:秒）
            minutes, seconds = divmod(page['duration'], 60)
            duration_str = f"{minutes:02d}:{seconds:02d}"
            text.append(
                f"第{page['page']}集 - 时长: {duration_str} - <{page['part']}>\n",
                style="bold white"
            )

    # 使用 Panel 包裹内容
    panel = Panel(
        text,
        title="🎬 视频信息",
        title_align="left",
        border_style="bright_blue",
        padding=(1, 2),
    )

    console.print(panel)



def parse(url: str, headers: dict):
    with requests.Session() as session:
        try:
            response = session.get(url=url, headers=headers, timeout=5)
            response.raise_for_status()

            html = response.text
            title = extract_title(html)
            playinfo = extract_playinfo_json(html)
            initial_state = extract_initial_state_json(html)
            playurl_ssr_data = extract_playurl_ssr_data(html)
            return {
                'title': title,
                'playinfo': playinfo,
                'initial_state': initial_state,
                'playurl_ssr_data': playurl_ssr_data,
            }
        except HTTPError:
            app_logger.exception(f'HTTP 错误')
        except RequestException:
            app_logger.exception(f'下载失败，网络请求错误')
        except Exception:
            app_logger.exception(f'未知错误')
    return None


def download_stream(url: str, headers, filename: str, progress):
    task = progress.add_task(f'{shrink_title(filename)}', start=False)
    with httpx.Client(proxy=None, trust_env=False).stream("GET", url=url, headers=headers) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get('Content-Length', 0))
        progress.update(task, total=total)
        progress.start_task(task)
        with open(filename, 'wb') as f:
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                f.write(chunk)
                progress.update(task, advance=len(chunk))


def download_sync(
        url: str,
        headers: dict,
        quality: Optional[int] = None,
        codec: Optional[str] = None,
        save: str = None,
):
    parse_res = parse(url, headers)
    title = parse_res.get('title')
    playinfo = parse_res.get('playinfo')
    playurl_info = parse_res.get('playurl_ssr_data')

    if playurl_info:
        dash = playurl_info['result'].get('video_info').get('dash')
        videos = dash.get('video', [])
        audios = dash.get('audio', [])
    else:
        if not playinfo or 'data' not in playinfo:
            app_logger.error(f"无法获取该 URL : {url} 的播放信息, 请检查该视频地址的正确性或者该视频的下载需要大会员账号权限")
            raise typer.Exit(code=1)

        dash = playinfo['data'].get('dash', {})
        videos = dash.get('video', [])
        audios = dash.get('audio', [])
        if not videos or not audios:
            app_logger.error("未检测到视频或音频流，退出。")
            raise typer.Exit(code=1)

    # 获取目标 codec 的 codecid，如果无效则默认使用 AVC
    target_codecid = codec_name_id_map.get(codec.upper(), 7) if codec else 7
    # 选择视频流
    selected = None
    if quality:
        # 优先匹配 id 和目标 codec
        selected = next((v for v in videos if v['id'] == quality and v.get('codecid') == target_codecid), None)
        if not selected:
            app_logger.info(f"未找到 {codec or 'AVC'} 格式的清晰度 {quality}，使用该格式中最高质量。")

    # 如果未指定 quality 或找不到对应流，就选该 codec 中 id 最大的
    if not selected:
        filtered_videos = [v for v in videos if v.get('codecid') == target_codecid]
        if filtered_videos:
            selected = max(filtered_videos, key=lambda v: v['id'])
        else:
            app_logger.warning(f"未找到 {codec or 'AVC'} 格式的视频，使用第一个可用视频流。")
            selected = videos[0]

    app_logger.info(f'选择下载的清晰度: {quality_id_name_map[selected["id"]]}, 格式: {codec_dict[selected["codecid"]]}')
    app_logger.info(f'视频标题: {title}')

    video_url = selected.get('baseUrl') or selected.get('base_url')
    # 选择音频流（默认最高）
    audio = audios[0]
    audio_url = audio.get('baseUrl') or audio.get('base_url')

    video_file = f'{title}_v_{selected["id"]}.m4s'
    audio_file = f'{title}_a_{selected["id"]}.m4s'
    start = int(time.time() * 1000)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        # MofNCompleteColumn(),
        FileSizeColumn(),
        TotalFileSizeColumn(),
        SpinnerColumn(),
    ) as progress:
        with ThreadPoolExecutor(max_workers=2) as executor:
            executor.submit(download_stream, video_url, headers, video_file, progress)
            executor.submit(download_stream, audio_url, headers, audio_file, progress)


    end = int(time.time() * 1000)
    app_logger.info(f'下载音视频共耗时: {end - start} ms')

    if save:
        save_path = Path(save)
        save_path.mkdir(parents=True, exist_ok=True)
    else:
        save_path = Path('.')  # 当前目录
    output_path = save_path / f'{title}_{quality_id_name_map[selected["id"]]}_{codec_dict[target_codecid]}.mp4'
    if output_path.exists():
        app_logger.warning('目标MP4存在，进行删除')
        output_path.unlink()

    app_logger.info("所有流下载完成，使用 ffmpeg 合并音视频")
    merge_m4s_ffmpeg(video_file, audio_file, str(output_path))
    Path.unlink(Path(video_file), missing_ok=True)
    Path.unlink(Path(audio_file), missing_ok=True)