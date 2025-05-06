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

app = typer.Typer()

download_headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0',
    # 'Cookie': "buvid3=540B6FB2-1B27-D498-A1F7-10907A412CB986733infoc; b_nut=1744025886; _uuid=C5D104C28-ACBF-DF810-DF91-8101610677210AE87578infoc; buvid4=BA1213FD-FE34-2E73-8B05-7E3BB50BD20C87758-025040711-CGSA5pzOeV9DsZE7bM%2BBfg%3D%3D; rpdid=|(YYYYlm~Rl0J'u~RR|kl))); bmg_af_switch=1; bmg_src_def_domain=i0.hdslb.com; header_theme_version=CLOSE; enable_web_push=DISABLE; enable_feed_channel=ENABLE; home_feed_column=5; share_source_origin=COPY; timeMachine=0; bsource=search_bing; fingerprint=97770f12afdfa9faac377b5c807d3cf1; buvid_fp_plain=undefined; buvid_fp=97770f12afdfa9faac377b5c807d3cf1; bp_t_offset_3305808=1057860800170950656; SESSDATA=3cb308bf%2C1760791532%2C48fff%2A41CjBTMeWaVU4f3fMPe7eG7J8QrQlAHWZJrx_Uoj_HmlkeQUwiy2-aJSMY8oXK6kbfaRkSVlBsRWJ0THVxRjBDOVlQSU41a3F2bEVxRlhhSmdGQktGYzRfZy03UnllNUZ3a180MjJiUDdCZnVwdmNwUE9CbDE0LVFTZTlyVDBPV0U0ekIyd3NBblhRIIEC; bili_jct=131de20e14a0a2796550bdc95ec13640; DedeUserID=384605143; DedeUserID__ckMd5=c089376be03f8134; VIP_DEFINITION_GUIDE=1; sid=7g7fnd8u; bili_ticket=eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NDYxMDExNTgsImlhdCI6MTc0NTg0MTg5OCwicGx0IjotMX0.fg5s3uXvEcONxAgLKCLpuyk3BUT0yOU3bajsp97Dmj8; bili_ticket_expires=1746101098; browser_resolution=1672-838; VIP_CONTENT_REMIND=1; CURRENT_QUALITY=0; b_lsid=E416A7A7_19689693B8E; bp_t_offset_384605143=1061820510909759488; CURRENT_FNVAL=4048"
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
        login:   bool          = Option(False, "-l", "--login", is_flag=True, help="登录"),
        ffmpeg:  Optional[str] = Option(None, "-f", "--ffmpeg", help="指定 ffmpeg 可执行文件路径"),
) -> None:
    """
    下载 Bilibili 视频及音频流，并提供清晰度选择。
    """

    if login:
        qrcode_key_res = qrcode_img()
        cookie = get_cookie(qrcode_key_res)
        with open('cookie.txt', 'w', encoding='utf-8') as f:
            f.write(cookie)
            app_logger.info('cookie 写入本地文件成功')
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
        # asyncio.run(download_async(url, headers, quality))
        # download_sync(urls, headers, quality, )

        if info:
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
