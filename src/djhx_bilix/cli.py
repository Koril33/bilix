import re
from pathlib import Path
from typing import Annotated, List

import typer
from typer import Option, Argument

from .account import user_login, user_info, user_logout
from .config.app_config import read_config, USER_DOWNLOAD_DIR_PATH
from .tool import clean_bili_url, parse_page_input
from .video import BiliTask, parse, get_bangumi_episode
from .video.video_info import create_bili_video

user_config = read_config()
app = typer.Typer()

@app.command()
def user(
    login:  Annotated[bool, Option('-l', '--login', help='登录账号')] = False,
    logout: Annotated[bool, Option('--logout', help='退出账号')] = False,
    info:   Annotated[bool, Option('-i', '--info', help='查看当前账号信息')] = True
):
    if login:
        user_login()
        return
    if logout:
        user_logout()
        return
    if info:
        user_info()
        return


@app.command()
def video(
    urls:       Annotated[List[str], Argument(help='一个或多个视频 URL')] = None,
    info:       Annotated[bool, Option('-i', '--info', help='查看视频信息')] = False,
    quality:    Annotated[int, Option('-q', '--quality', help='视频清晰度 | 120: 4K | 112: 1080P+ | 80: 1080P | 64: 720P | 32: 480P | 16: 360P |')] = None,
    codec:      Annotated[str, Option('--codec', help='指定下载视频的编码格式 | AVC | HEVC | AV1 |')] = None,
    save:       Annotated[Path, Option('-s', '--save')] = USER_DOWNLOAD_DIR_PATH,
    page:       Annotated[str, Option('-p', '--page', help='指定要下载的集数，例如 -p 3、-p 1,4,9、-p 4-12；不指定值表示下载全部')] = None,
):
    urls = validate_urls(urls)
    if info:
        for url in urls:
            create_bili_video(url).show()
        return

    if len(urls) == 1 and page:
        page_parsed = parse_page_input(page)
        url = clean_bili_url(urls[0])

        # 下载番剧
        if 'bangumi/media' in url:
            md_id = url.split('/')[-1]
            typer.echo(f'准备下载番剧, md_id: {md_id}')
            episodes = get_bangumi_episode(md_id)

            if page_parsed != "all":
                # 只保留索引在 page_parsed 中指定的集数（从 1 开始）
                episodes = [episodes[i - 1] for i in page_parsed if 1 <= i <= len(episodes)]

            typer.echo(f'检测到番剧集合, 待下载总数: {len(episodes)}')
            for episode in episodes:
                BiliTask(url=episode['share_url'], quality=quality, codec=codec, save=save).download()
        # 下载普通多集视频
        else:
            typer.echo(f'准备下载视频集合, page={page_parsed}')

            initial_state = parse(url).get('initial_state')
            video_pages = initial_state['videoData']['pages']
            page_nums = [p['page'] for p in video_pages]
            if len(video_pages) > 1:
                download_page_nums = page_nums if page_parsed == 'all' else page_parsed
                typer.echo(f'检测到视频集合, 待下载总数: {len(download_page_nums)}, 集数: {download_page_nums}')
                for page in download_page_nums:
                    BiliTask(url=f'{url}?p={page}', quality=quality, codec=codec, save=save).download()
    else:
        for url in urls:
            clean_url = clean_bili_url(url)
            BiliTask(url=clean_url, quality=quality, codec=codec, save=save).download()



def validate_urls(urls: List[str], max_len: int = 10) -> List[str]:
    if not urls:
        raise typer.BadParameter("请指定至少一个 Bilibili 视频 URL")
    if len(urls) > max_len:
        raise typer.BadParameter(f"最多只能指定 {max_len} 个 URL")

    # 简单 URL 校验
    url_pattern = re.compile(r'https?://(www\.)?bilibili\.com/.*')
    for url in urls:
        if not url_pattern.match(url):
            raise typer.BadParameter(f"无效的 Bilibili URL: {url}")

    return urls