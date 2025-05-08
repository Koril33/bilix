import copy
import time
from pathlib import Path
from typing import Annotated, Optional, List

import typer
from typer import Option, Argument

from download_sync import download_sync, parse, get_video_info
from log_config import app_logger, log_init
from login import qrcode_img, get_cookie
from tool import load_urls_from_file, clean_bili_url
from user import get_user_info

__version__ = "v1.0.0"

def version_callback(value: bool):
    if value:
        app_logger.info(f"bilix version: {__version__}")
        raise typer.Exit()

app = typer.Typer()

download_headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
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
        urls:    Annotated[List[str], Argument(help="一个或多个目标视频 URL")] = None,
        quality: Optional[int] = Option(None, "-q", "--quality", help="视频清晰度 | 120: 4K | 112: 1080P+ | 80: 1080P | 64: 720P | 32: 480P | 16: 360P |"),
        origin:  Optional[str] = Option(None, "-o", "--origin", help="指定下载来源文件路径"),
        save:    Optional[str] = Option(None, "-s", "--save", help="指定下载结果保存目录路径"),
        page:    bool          = Option(False, "-p", "--page", is_flag=True, help="是否下载多集视频"),
        info:    bool          = Option(False, "-i", "--info", is_flag=True, help="是否仅获取视频信息"),
        login:   bool          = Option(False, "-l", "--login", is_flag=True, help="登录账号"),
        logout:  bool          = Option(False, "--logout", is_flag=True, help="退出账号"),
        user:    bool          = Option(False, "-u", "--user", is_flag=True, help="当前账号信息"),
        version: Annotated[Optional[bool], typer.Option("-v", "--version", callback=version_callback, is_eager=True, help="查看软件版本信息"),] = None,
) -> None:
    """
    下载 Bilibili 视频的命令行工具，支持账号登陆，下载视频，选择清晰度下载等功能
    """

    if user:
        cookie_file = Path('cookie.txt')
        if cookie_file.is_file():
            h = copy.deepcopy(download_headers)
            h['cookie'] = cookie_file.read_text()
            get_user_info(h)
            return
        else:
            app_logger.warning('用户未登录, 登录请使用 --login 选项')
        return

    if login:
        qrcode_key_res = qrcode_img()
        cookie = get_cookie(qrcode_key_res)
        with open('cookie.txt', 'w', encoding='utf-8') as f:
            f.write(cookie)
            app_logger.info('cookie 写入本地文件成功')
        return

    if logout:
        cookie_file = Path('cookie.txt')
        if cookie_file.is_file():
            cookie_file.unlink()
            app_logger.info('退出账号成功')
        else:
            app_logger.warning('用户未登录, 登录请使用 --login 选项')
        return

    if not urls and not origin:
        app_logger.error('请提供 urls 或 --origin 中的一个')
        raise typer.Exit(code=1)

    if Path('cookie.txt').is_file():
        app_logger.info(f'找到 cookie.txt 文件')
        download_headers['Cookie'] = open('cookie.txt', 'r', encoding='utf-8').read()
    else:
        app_logger.warning(f'未找到 cookie.txt 文件')

    start = int(time.time() * 1000)
    try:
        if info:
            app_logger.info(f"获取 {len(urls)} 个视频信息")
            for url in urls:
                h = copy.deepcopy(download_headers)
                h['Referer'] = url
                get_video_info(url, h)
            return

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
