import copy
import time
from typing import Annotated, Optional, List
from urllib.parse import urlparse, urlunparse, urlsplit, urlunsplit

import typer
from typer import Option

from download_sync import download_sync, parse
from log_config import app_logger, log_init
from tool import load_urls_from_file, clean_bili_url

app = typer.Typer()

download_headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0',
    'Cookie': "buvid3=3811CC7E-3BE1-947B-CC72-CEDB7A76FEFF35698infoc; b_nut=1724035335; _uuid=F8C1A6104-4788-DF43-4F11-BB2B65BC45CB36192infoc; buvid4=EAD0F3DB-F24E-D549-2229-54EFCF89D26637266-024081902-6GVRa3OrrpMoc68dd1U5zQ%3D%3D; bmg_af_switch=1; bmg_src_def_domain=i0.hdslb.com; header_theme_version=CLOSE; enable_web_push=DISABLE; rpdid=|(J|~)m~)YYu0J'u~kRukY~|J; buvid_fp_plain=undefined; hit-dyn-v2=1; DedeUserID=3305808; DedeUserID__ckMd5=7bb2e1b458a07561; enable_feed_channel=ENABLE; fingerprint=41616665b9dabc452ecc04afbe6067b2; buvid_fp=41616665b9dabc452ecc04afbe6067b2; share_source_origin=WEIXIN; CURRENT_QUALITY=0; home_feed_column=5; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NDU5NzQ1NzUsImlhdCI6MTc0NTcxNTMxNSwicGx0IjotMX0.eiidO8DseBfQKKXHZRmoh01E81kgBVjjNR9OZDoy1Dc; bili_ticket_expires=1745974515; bp_t_offset_3305808=1060368738949267456; SESSDATA=1e10c871%2C1761382965%2C7cfdb%2A41CjAxYrw-Q651dnlPn61AQwH7cLd_8bBDzpvKm1pkl305654xW-6hBjV9-Dv5oFGzCacSVm0xTUhHQkZZNERQS1BKSmVSb3NEaEh1N040TURYQVd6eExBQk5YR3EzbWNCdTV0b010SFRjal9XVk9NeWtpRGFVRmc0LTdyOFF2b3N6V0xxc2luaE1BIIEC; bili_jct=c81455f2096b7791f376fc144b85f8db; sid=7tsepjcu; b_lsid=CCDC86BE_1967F1170C6; bsource=search_bing; browser_resolution=1650-762; CURRENT_FNVAL=4048"
}

class BiliTask:
    def __init__(self, url: str, headers: dict, quality: int, save: str):
        self.url = url
        self.headers = headers
        self.quality = quality
        self.save = save

    def download(self):
        download_sync(self.url, self.headers, self.quality, self.save)


@app.command()
def download(
        urls: Annotated[List[str], typer.Argument(help="一个或多个目标视频 URL")] = None,
        quality: Optional[int] = Option(None, "-q", "--quality", help="视频清晰度"),
        origin: Optional[str] = Option(None, "-o", "--origin", help="指定下载来源文件路径"),
        save: Optional[str] = Option(None, "-s", "--save", help="指定下载结果保存目录路径"),
        page: bool = typer.Option(False, "-p", "--page", is_flag=True, help="是否下载多集视频"),
        ffmpeg: Optional[str] = Option(None, "-f", "--ffmpeg", help="指定 ffmpeg 可执行文件路径"),
) -> None:
    """
    下载 Bilibili 视频及音频流，并提供清晰度选择。
    """

    if not urls and not origin:
        app_logger.error('请提供 urls 或 --origin 中的一个')
        raise typer.Exit(code=1)

    start = int(time.time() * 1000)
    try:
        # asyncio.run(download_async(url, headers, quality))
        # download_sync(urls, headers, quality, )
        if origin:
            app_logger.info(f'用户指定URL文件: {origin}')
            urls = load_urls_from_file(origin)
        app_logger.info(f'开始下载, 共计: {len(urls)} 个任务')

        if len(urls) == 1 and page:
            h = copy.deepcopy(download_headers)
            url = clean_bili_url(urls[0])
            h['Referer'] = url
            initial_state = parse(url, headers=h).get('initial_state')
            video_pages = initial_state['videoData']['pages']
            if len(video_pages) > 1:
                app_logger.info(f'检测到视频集合')
                for page in video_pages:
                    BiliTask(url=f'{url}?p={page["page"]}', headers=h, quality=quality, save=save).download()
        for url in urls:
            clean_url = clean_bili_url(url)
            h = copy.deepcopy(download_headers)
            h['Referer'] = clean_url
            BiliTask(url=clean_url, headers=h, quality=quality, save=save).download()

    except Exception:
        app_logger.exception(f"下载过程中出现错误")
        raise typer.Exit(code=1)
    finally:
        end = int(time.time() * 1000)
        app_logger.info(f'总耗时: {end - start} ms')


if __name__ == '__main__':
    log_init()
    app()
