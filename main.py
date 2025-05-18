import copy
import sys
import time
from pathlib import Path
from typing import Annotated, Optional, List

import typer
from typer import Option, Argument

from download_sync import download_sync, parse, get_bangumi_episode
from log_config import app_logger, log_init
from login import qrcode_img, get_cookie
from tool import load_urls_from_file, clean_bili_url, parse_page_input
from update import update_exe
from user import get_user_info

__version__ = "v1.2.2"

from video_info import create_bili_video


def version_callback(value: bool):
    if value:
        app_logger.info(f"bilix version: {__version__}")
        raise typer.Exit()

app = typer.Typer()

download_headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
}

class BiliTask:
    def __init__(self, url: str, headers: dict, quality: int, codec:str, save: str):
        self.url = url
        self.headers = headers
        self.quality = quality
        self.codec = codec
        self.save = save

    def download(self):
        download_sync(self.url, self.headers, self.quality, self.codec, self.save)


@app.command()
def download(
        urls:    Annotated[List[str], Argument(help="一个或多个目标视频 URL")] = None,
        quality: Optional[int] = Option(None, "-q", "--quality", help="视频清晰度 | 120: 4K | 112: 1080P+ | 80: 1080P | 64: 720P | 32: 480P | 16: 360P |"),
        origin:  Optional[str] = Option(None, "-o", "--origin", help="指定下载来源文件路径"),
        save:    Optional[str] = Option(None, "-s", "--save", help="指定下载结果保存目录路径"),
        page:    Optional[str] = Option(None, "-p", "--page", help="指定要下载的集数，例如 -p 3、-p 1,4,9、-p 4-12；不指定值表示下载全部"),
        info:    bool          = Option(False, "-i", "--info", is_flag=True, help="是否仅获取视频信息"),
        login:   bool          = Option(False, "-l", "--login", is_flag=True, help="登录账号"),
        logout:  bool          = Option(False, "--logout", is_flag=True, help="退出账号"),
        user:    bool          = Option(False, "-u", "--user", is_flag=True, help="当前账号信息"),
        codec:   Optional[str] = Option(None, "--codec", help="指定下载视频的编码格式 | AVC | HEVC | AV1 |"),
        update:  bool          = Option(False, "--update", is_flag=True, help="更新程序"),
        version: Annotated[Optional[bool], typer.Option("-v", "--version", callback=version_callback, is_eager=True, help="查看软件版本信息"),] = None,
) -> None:
    """
    下载 Bilibili 视频的命令行工具，支持账号登陆，下载视频，选择清晰度下载等功能
    """

    if update:
        update_exe(__version__)
        return

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
        app_logger.error('请提供一个视频 URL 进行下载，或者查看 --help 帮助信息')
        sys.exit(1)

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
                # get_video_info(url, h)
                create_bili_video(url, h).show()
            return

        if origin:
            app_logger.info(f'用户指定URL文件: {origin}')
            urls = load_urls_from_file(origin)
        app_logger.info(f'开始下载, 共计: {len(urls)} 个任务')

        if len(urls) == 1 and page:
            page_parsed = parse_page_input(page)
            url = clean_bili_url(urls[0])
            h = copy.deepcopy(download_headers)
            h['Referer'] = url

            # 下载番剧
            if 'bangumi/media' in url:
                md_id = url.split('/')[-1]
                app_logger.info(f'准备下载番剧, md_id: {md_id}')
                episodes = get_bangumi_episode(md_id)

                if page_parsed != "all":
                    # 只保留索引在 page_parsed 中指定的集数（从 1 开始）
                    episodes = [episodes[i - 1] for i in page_parsed if 1 <= i <= len(episodes)]

                app_logger.info(f'检测到番剧集合, 待下载总数: {len(episodes)}')
                for episode in episodes:
                    BiliTask(url=episode['share_url'], headers=h, quality=quality, codec=codec, save=save).download()
            # 下载普通多集视频
            else:
                app_logger.info(f'准备下载视频集合, page={page_parsed}')

                initial_state = parse(url, headers=h).get('initial_state')
                video_pages = initial_state['videoData']['pages']
                page_nums = [p['page'] for p in video_pages]
                if len(video_pages) > 1:
                    download_page_nums = page_nums if page_parsed == 'all' else page_parsed
                    app_logger.info(f'检测到视频集合, 待下载总数: {len(download_page_nums)}, 集数: {download_page_nums}')
                    for page in download_page_nums:
                        BiliTask(url=f'{url}?p={page}', headers=h, quality=quality, codec=codec, save=save).download()
        else:
            for url in urls:
                clean_url = clean_bili_url(url)
                h = copy.deepcopy(download_headers)
                h['Referer'] = clean_url
                BiliTask(url=clean_url, headers=h, quality=quality, codec=codec, save=save).download()

    except Exception:
        app_logger.exception(f"下载过程中出现错误")
        sys.exit(1)
    finally:
        end = int(time.time() * 1000)
        app_logger.info(f'总耗时: {end - start} ms')


if __name__ == '__main__':
    log_init()
    app()
