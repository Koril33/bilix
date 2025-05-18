import json
import math
from abc import abstractmethod
from collections import OrderedDict, defaultdict
from datetime import datetime

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException, HTTPError
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from global_param import codec_id_name_map
from log_config import app_logger
from tool import clean_bili_url, sanitize_filename
import re

console = Console()

class BiliVideoInfo:

    playinfo_pattern = r'window\.__playinfo__\s*=\s*(\{.*?})\s*</script>'
    initial_state_pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?})\s*;'
    playurl_ssr_data_pattern = r'const\s+playurlSSRData\s*=\s*({.*?})\s'
    title_pattern = r'<title\b[^>]*>(.*?)</title>'

    def __init__(self, url, headers):
        if not self.check_url_valid(url):
            raise ValueError(f"Invalid Bilibili URL: {url}")
        self.url = url
        self.headers = headers
        self.playinfo = None
        self.initial_state = None
        self.playurl_ssr_data = None
        self.title = None

    @staticmethod
    def check_url_valid(url: str) -> bool:
        pattern = re.compile(
            r"^https://www\.bilibili\.com/(?:"  # 固定前缀
            r"video/BV[0-9A-Za-z]+|"  # 1. 视频：BV号
            r"bangumi/play/(?:ep\d+|ss\d+)|"  # 2. 番剧：ep 或 ss
            r"bangumi/media/md\d+"  # 3. 媒体库：md号
            r")/?$"  # 可选的结尾斜杠
        )
        return bool(pattern.match(clean_bili_url(url)))

    @staticmethod
    def extract_json(pattern: str, text: str):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                app_logger.warning(f'JSON decode failed for pattern: {pattern}')
        return None

    @classmethod
    def from_url(cls, url: str, headers: dict):
        instance = cls(url, headers)
        instance.parse()
        return instance

    @abstractmethod
    def show(self):
        pass

    def extract_video_time_length(self):
        return self.playinfo.get('data').get('timelength')

    def get_video_bvid(self):
        if self.initial_state:
            return self.initial_state.get('bvid')
        else:
            result = self.playurl_ssr_data.get('result')
            raw = self.playurl_ssr_data.get('raw')
            if result:
                return result.get('play_view_business_info').get('episode_info').get('bvid')
            elif raw:
                return raw.get('data').get('arc').get('bvid')
        raise ValueError('无法获取 bvid')

    def get_bvid_info(self):
        bvid = self.get_video_bvid()
        bvid_info_url = 'https://api.bilibili.com/x/web-interface/wbi/view'
        bvid_resp = requests.get(bvid_info_url, headers=self.headers, params={'bvid': bvid}, timeout=5)
        bvid_resp_json = bvid_resp.json()
        bvid_data = bvid_resp_json['data']
        return {
            'tname': bvid_data['tname'],
            'tname_v2': bvid_data['tname_v2'],
            'pubdate': bvid_data['pubdate'],
            'ctime': bvid_data['ctime'],
            'desc': bvid_data['desc'],
            'owner': bvid_data['owner'],
        }

    def extract(self, html_content: str):
        self.playinfo = self.extract_json(self.playinfo_pattern, html_content)
        self.initial_state = self.extract_json(self.initial_state_pattern, html_content)
        self.playurl_ssr_data = self.extract_json(self.playurl_ssr_data_pattern, html_content)

        title_match = re.search(self.title_pattern, html_content, re.IGNORECASE | re.DOTALL)
        if title_match:
            self.title = sanitize_filename(title_match.group(1).strip())
            # bangumi/media/md 无法提取到 title 需要特殊处理
            if not self.title and self.initial_state:
                self.title = sanitize_filename(self.initial_state.get('mediaInfo').get('title'))

    def parse(self):
        try:
            resp = requests.get(self.url, headers=self.headers, timeout=5)
            resp.raise_for_status()
            self.extract(resp.text)
        except HTTPError:
            app_logger.exception(f'HTTP error')
        except RequestException:
            app_logger.exception(f'Request error')


class BiliNormalVideo(BiliVideoInfo):
    def __init__(self, url, headers):
        super().__init__(url, headers)
        self.parse()
        self.time_length = self.extract_video_time_length()
        self.bvid_info = self.get_bvid_info()


    def show(self):

        text = Text()
        table = Table(title="可选择清晰度")
        group = Group(text, table)
        panel = Panel(group, title="普通视频信息", title_align="center", border_style="bright_yellow", padding=(1, 2),  expand=False)

        playinfo_data = self.playinfo.get('data')

        video_total_seconds = math.ceil(self.time_length / 1000)
        video_minutes, video_seconds = divmod(video_total_seconds, 60)

        basic_style = 'bold cyan'
        section_style = 'bold magenta'
        desc_style = 'bold red'
        user_style = 'bold white'

        date_style = 'orange1'

        info_style = 'bold green'


        text.append('视频 URL: ', basic_style).append(f'{self.url}\n', info_style)
        text.append('视频标题: ', basic_style).append(f'{self.title}\n', info_style)
        text.append('视频格式: ', basic_style).append(f'{playinfo_data.get('format')}\n', info_style)
        text.append('视频 aid: ', basic_style).append(f'{self.initial_state.get('aid')}\n', info_style)
        text.append('视频 bvid: ', basic_style).append(f'{self.initial_state.get('bvid')}\n', info_style)
        text.append('视频 cid: ', basic_style).append(f'{self.initial_state.get('cid')}\n', info_style)
        text.append('视频时长: ', basic_style).append(f'{video_minutes} 分 {video_seconds} 秒\n\n', info_style)

        text.append('子分区信息: ', section_style).append(f'{self.bvid_info['tname']}\n', info_style)
        text.append('子分区信息_v2: ', section_style).append(f'{self.bvid_info['tname_v2']}\n\n', info_style)

        text.append('稿件发布时间: ', date_style).append(f'{datetime.fromtimestamp(self.bvid_info['pubdate']).strftime('%Y-%m-%d %H:%M:%S')}\n', info_style)
        text.append('用户投稿时间: ', date_style).append(f'{datetime.fromtimestamp(self.bvid_info['ctime']).strftime('%Y-%m-%d %H:%M:%S')}\n\n', info_style)

        text.append('视频 UP 主 mid: ', user_style).append(f'{self.bvid_info['owner']['mid']}\n', info_style)
        text.append('视频 UP 主用户名: ', user_style).append(f'{self.bvid_info['owner']['name']}\n\n', info_style)

        text.append('视频简介: ', desc_style).append(f'{self.bvid_info['desc']}\n', info_style)

        accept_quality = playinfo_data['accept_quality']
        accept_description = playinfo_data['accept_description']
        dash_video = playinfo_data['dash']['video']
        qualities = OrderedDict(zip(accept_quality, accept_description))

        codecid_dict = defaultdict(list)
        for v in dash_video:
            codecid_dict[v['id']].append(codec_id_name_map.get(v['codecid']))

        table.add_column("id", justify="center", style="cyan", no_wrap=True)
        table.add_column("name", style="blue")
        table.add_column("codec", justify="center", style="green")

        for resolution_id, resolution_name in qualities.items():
            codec_list = codecid_dict.get(resolution_id)
            if codec_list:
                codec_str = '/'.join(codec_list)
            else:
                codec_str = '需登录相应权限的账号'
            table.add_row(str(resolution_id), resolution_name, codec_str)

        console.print(panel)


class BiliMultiPartVideo(BiliVideoInfo):
    def __init__(self, url, headers):
        super().__init__(url, headers)
        self.parse()
        self.time_length = self.extract_video_time_length()
        self.bvid_info = self.get_bvid_info()
        self.pages_info = self.extract_pages()


    def extract_pages(self):
        """
        提取选集信息
        """
        return self.initial_state.get('videoData').get('pages')

    def show(self):

        text = Text()
        table = Table(title="可选择清晰度")
        pages_table = Table(title="选集信息")
        group = Group(text, table, pages_table)
        panel = Panel(group, title="多集视频信息", title_align="center", border_style="bright_blue", padding=(1, 2),  expand=False)

        playinfo_data = self.playinfo.get('data')

        video_total_seconds = math.ceil(self.time_length / 1000)
        video_minutes, video_seconds = divmod(video_total_seconds, 60)

        basic_style = 'bold cyan'
        section_style = 'bold magenta'
        desc_style = 'bold red'
        user_style = 'bold white'

        date_style = 'orange1'

        info_style = 'bold green'


        text.append('视频 URL: ', basic_style).append(f'{self.url}\n', info_style)
        text.append('视频标题: ', basic_style).append(f'{self.title}\n', info_style)
        text.append('视频格式: ', basic_style).append(f'{playinfo_data.get('format')}\n', info_style)
        text.append('视频 aid: ', basic_style).append(f'{self.initial_state.get('aid')}\n', info_style)
        text.append('视频 bvid: ', basic_style).append(f'{self.initial_state.get('bvid')}\n', info_style)
        text.append('视频 cid: ', basic_style).append(f'{self.initial_state.get('cid')}\n', info_style)
        text.append('视频时长: ', basic_style).append(f'{video_minutes} 分 {video_seconds} 秒\n\n', info_style)

        text.append('子分区信息: ', section_style).append(f'{self.bvid_info['tname']}\n', info_style)
        text.append('子分区信息_v2: ', section_style).append(f'{self.bvid_info['tname_v2']}\n\n', info_style)

        text.append('稿件发布时间: ', date_style).append(f'{datetime.fromtimestamp(self.bvid_info['pubdate']).strftime('%Y-%m-%d %H:%M:%S')}\n', info_style)
        text.append('用户投稿时间: ', date_style).append(f'{datetime.fromtimestamp(self.bvid_info['ctime']).strftime('%Y-%m-%d %H:%M:%S')}\n\n', info_style)

        text.append('视频 UP 主 mid: ', user_style).append(f'{self.bvid_info['owner']['mid']}\n', info_style)
        text.append('视频 UP 主用户名: ', user_style).append(f'{self.bvid_info['owner']['name']}\n\n', info_style)

        text.append('视频简介: ', desc_style).append(f'{self.bvid_info['desc']}\n', info_style)

        accept_quality = playinfo_data['accept_quality']
        accept_description = playinfo_data['accept_description']
        dash_video = playinfo_data['dash']['video']
        qualities = OrderedDict(zip(accept_quality, accept_description))

        codecid_dict = defaultdict(list)
        for v in dash_video:
            codecid_dict[v['id']].append(codec_id_name_map.get(v['codecid']))

        table.add_column("id", justify="center", style="cyan", no_wrap=True)
        table.add_column("name", style="blue")
        table.add_column("codec", justify="center", style="green")

        for resolution_id, resolution_name in qualities.items():
            codec_list = codecid_dict.get(resolution_id)
            if codec_list:
                codec_str = '/'.join(codec_list)
            else:
                codec_str = '需登录相应权限的账号'
            table.add_row(str(resolution_id), resolution_name, codec_str)


        # 选集信息展示
        pages_table.add_column("index", justify="center", style="cyan", no_wrap=True)
        pages_table.add_column("name", style="blue")
        pages_table.add_column("duration", justify="center", style="green")
        for page in self.pages_info:
            minutes, seconds = divmod(page['duration'], 60)
            duration_str = f'{minutes:02d}:{seconds:02d}'
            pages_table.add_row(str(page['page']), page['part'], duration_str)


        console.print(panel)


class BiliMovie(BiliVideoInfo):
    def __init__(self, url, headers):
        super().__init__(url, headers)
        self.parse()


    def show(self):
        text = Text()
        group = Group(text)
        panel = Panel(group, title="电影信息", title_align="center", border_style="magenta", padding=(1, 2), expand=False)

        basic_style = 'bold cyan'
        desc_style = 'bold red'

        info_style = 'bold green'

        text.append('电影 URL: ', basic_style).append(f'{self.url}\n', info_style)
        text.append('电影标题: ', basic_style).append(f'{self.title}\n', info_style)

        if self.initial_state:
            movie_desc = self.initial_state['mediaInfo']['evaluate']
        else:
            movie_desc = '暂无介绍'

        text.append('电影简介: ', desc_style).append(f'{movie_desc}\n', info_style)

        console.print(panel)


class BiliBangumi(BiliVideoInfo):
    def __init__(self, url, headers):
        super().__init__(url, headers)
        self.parse()
        self.episodes = self.get_bangumi_episodes()

    def get_bangumi_episodes(self):
        md_id = self.url.split('/')[-1].replace('md', '')
        if 'ep' in md_id:
            return None
        url1 = f'https://api.bilibili.com/pgc/review/user?media_id={md_id}'
        resp1 = requests.get(url1, timeout=5)
        resp1.raise_for_status()
        season_id = resp1.json()['result']['media']['season_id']

        url2 = f'https://api.bilibili.com/pgc/web/season/section?season_id={season_id}'
        resp2 = requests.get(url2, timeout=5)
        resp2.raise_for_status()
        episodes = resp2.json()['result']['main_section']['episodes']
        return episodes

    def show(self):
        text = Text()
        pages_table = Table(title="选集信息")
        group = Group(text, pages_table)
        panel = Panel(group, title="番剧信息", title_align="center", border_style="bright_green", padding=(1, 2), expand=False)

        basic_style = 'bold cyan'
        desc_style = 'bold red'

        info_style = 'bold green'

        text.append('番剧 URL: ', basic_style).append(f'{self.url}\n', info_style)
        text.append('番剧标题: ', basic_style).append(f'{self.title}\n', info_style)
        text.append('番剧简介: ', desc_style).append(f'{self.initial_state['mediaInfo']['evaluate']}\n', info_style)

        # 选集信息展示
        pages_table.add_column("index", justify="center", style="cyan", no_wrap=True)
        pages_table.add_column("name", style="blue")

        for episode in self.episodes:
            pages_table.add_row(str(episode['title']), episode['long_title'])

        console.print(panel)


class BiliOther(BiliVideoInfo):
    def __init__(self, url, headers):
        super().__init__(url, headers)
        self.parse()
        self.episodes = self.get_bangumi_episodes()

    def get_bangumi_episodes(self):
        md_id = self.url.split('/')[-1].replace('md', '')
        if 'ep' in md_id:
            return None
        url1 = f'https://api.bilibili.com/pgc/review/user?media_id={md_id}'
        resp1 = requests.get(url1, timeout=5)
        resp1.raise_for_status()
        season_id = resp1.json()['result']['media']['season_id']

        url2 = f'https://api.bilibili.com/pgc/web/season/section?season_id={season_id}'
        resp2 = requests.get(url2, timeout=5)
        resp2.raise_for_status()
        episodes = resp2.json()['result']['main_section']['episodes']
        return episodes

    def show(self):
        text = Text()
        pages_table = Table(title="选集信息")
        group = Group(text, pages_table)
        panel = Panel(group, title="其他类型剧集信息", title_align="center", border_style="dark_red", padding=(1, 2), expand=False)

        basic_style = 'bold cyan'
        desc_style = 'bold red'

        info_style = 'bold green'

        text.append('剧集 URL: ', basic_style).append(f'{self.url}\n', info_style)
        text.append('剧集标题: ', basic_style).append(f'{self.title}\n', info_style)
        text.append('剧集简介: ', desc_style).append(f'{self.initial_state['mediaInfo']['evaluate']}\n', info_style)

        # 选集信息展示
        pages_table.add_column("index", justify="center", style="cyan", no_wrap=True)
        pages_table.add_column("name", style="blue")

        for episode in self.episodes:
            pages_table.add_row(str(episode['title']), episode['long_title'])

        console.print(panel)


class BiliEpisode(BiliVideoInfo):
    def __init__(self, url, headers):
        super().__init__(url, headers)
        self.parse()
        self.bvid_info = self.get_bvid_info()


    def show(self):
        text = Text()
        table = Table(title="可选择清晰度")
        group = Group(text, table)

        panel = Panel(group, title="剧集信息", title_align="center", border_style="bright_cyan", padding=(1, 2),
                      expand=False)

        basic_style = 'bold cyan'
        section_style = 'bold magenta'
        desc_style = 'bold red'
        user_style = 'bold white'

        date_style = 'orange1'

        info_style = 'bold green'

        text.append('单集 URL: ', basic_style).append(f'{self.url}\n', info_style)
        text.append('单集标题: ', basic_style).append(f'{self.title}\n', info_style)

        text.append('子分区信息: ', section_style).append(f'{self.bvid_info['tname']}\n', info_style)
        text.append('子分区信息_v2: ', section_style).append(f'{self.bvid_info['tname_v2']}\n\n', info_style)

        text.append('稿件发布时间: ', date_style).append(
            f'{datetime.fromtimestamp(self.bvid_info['pubdate']).strftime('%Y-%m-%d %H:%M:%S')}\n', info_style)
        text.append('用户投稿时间: ', date_style).append(
            f'{datetime.fromtimestamp(self.bvid_info['ctime']).strftime('%Y-%m-%d %H:%M:%S')}\n\n', info_style)

        text.append('视频 UP 主 mid: ', user_style).append(f'{self.bvid_info['owner']['mid']}\n', info_style)
        text.append('视频 UP 主用户名: ', user_style).append(f'{self.bvid_info['owner']['name']}\n\n', info_style)

        text.append('单集简介: ', desc_style).append(f'{self.bvid_info['desc']}\n', info_style)

        result = self.playurl_ssr_data.get('result')
        raw = self.playurl_ssr_data.get('raw')

        if result:
            video_info = result.get('video_info')
        elif raw:
            video_info = raw.get('data').get('video_info')
        else:
            raise ValueError('无法找到 video_info')

        accept_quality = video_info['accept_quality']
        accept_description = video_info['accept_description']

        qualities = OrderedDict(zip(accept_quality, accept_description))

        codecid_dict = defaultdict(list)
        if video_info.get('dash'):
            dash_video = video_info['dash']['video']
            for v in dash_video:
                codecid_dict[v['id']].append(codec_id_name_map.get(v['codecid']))
        elif video_info.get('durls'):
            durls = video_info.get('durls')
            for v in durls:
                codecid_dict[v['quality']].append('empty')


        table.add_column("id", justify="center", style="cyan", no_wrap=True)
        table.add_column("name", style="blue")
        table.add_column("codec", justify="center", style="green")

        for resolution_id, resolution_name in qualities.items():
            codec_list = codecid_dict.get(resolution_id)
            if codec_list:
                codec_str = '/'.join(codec_list)
            else:
                codec_str = '需登录相应权限的账号'
            table.add_row(str(resolution_id), resolution_name, codec_str)

        console.print(panel)


def create_bili_video(url: str, headers: dict) -> BiliVideoInfo:
    clean_url = clean_bili_url(url)
    bv = BiliVideoInfo.from_url(clean_url, headers)
    if 'video/BV' in clean_url:
        if len(bv.initial_state['videoData']['pages']) > 1:
            return BiliMultiPartVideo(url, headers)
        return BiliNormalVideo(url, headers)
    elif '/bangumi/play/' in clean_url:
        return BiliEpisode(url, headers)
    elif '/bangumi/media/md' in clean_url:
        type_name = bv.initial_state.get('mediaInfo').get('type_name')
        if type_name == '电影':
            return BiliMovie(url, headers)
        elif type_name == '番剧':
            return BiliBangumi(url, headers)
        else:
            return BiliOther(url, headers)
    else:
        raise ValueError(f"不支持的 URL: {url}")


def main():
    urls = [
        'https://www.bilibili.com/video/BV1yt4y1Q7SS/',
        'https://www.bilibili.com/video/BV12R4y1J75d',
        'https://www.bilibili.com/bangumi/play/ep806232',
        'https://www.bilibili.com/bangumi/play/ep1656974',
        'https://www.bilibili.com/bangumi/play/ss12548',
        'https://www.bilibili.com/bangumi/play/ss98687',
        'https://www.bilibili.com/bangumi/play/ss90684',
        'https://www.bilibili.com/bangumi/play/ep1562870',
        'https://www.bilibili.com/bangumi/play/ss89626',
        'https://www.bilibili.com/bangumi/play/ep332658',
        'https://www.bilibili.com/bangumi/play/ep332611',
        'https://www.bilibili.com/bangumi/media/md80952',
        'https://www.bilibili.com/bangumi/media/md1568',
        'https://www.bilibili.com/bangumi/media/md2014',
        'https://www.bilibili.com/bangumi/media/md21174614',
        'https://www.bilibili.com/bangumi/media/md27526419',
        'https://www.bilibili.com/bangumi/play/ep131360',
        'https://www.bilibili.com/bangumi/play/ep835824',
        'https://www.bilibili.com/bangumi/media/md22825846',
        'https://www.bilibili.com/bangumi/play/ss48056',
        'https://www.bilibili.com/bangumi/media/md22149965',
        'https://www.bilibili.com/bangumi/play/ep837088',
        'https://www.bilibili.com/bangumi/play/ep1646110',
        'https://www.bilibili.com/bangumi/play/ss38583',
        'https://www.bilibili.com/bangumi/play/ss76849',
        'https://www.bilibili.com/bangumi/play/ep1700499',
        'https://www.bilibili.com/bangumi/play/ss27042',
        'https://www.bilibili.com/bangumi/play/ep269127',
        'https://www.bilibili.com/bangumi/play/ss33343',
        'https://www.bilibili.com/bangumi/play/ep332658',
        'https://www.bilibili.com/bangumi/play/ep1550696',
        'https://www.bilibili.com/bangumi/media/md24078736',
        'https://www.bilibili.com/bangumi/media/md25581765',
        'https://www.bilibili.com/bangumi/play/ep1663133',
        'https://www.bilibili.com/bangumi/media/md26181752',
        'https://www.bilibili.com/bangumi/media/md23567884',
        'https://www.bilibili.com/bangumi/media/md20117',
        'https://www.bilibili.com/video/BV1zw68YsEP9',
        'https://www.bilibili.com/bangumi/play/ss44473',
        'https://www.bilibili.com/bangumi/media/md28480901',
        'https://www.bilibili.com/bangumi/play/ep1646110',
        'https://www.bilibili.com/bangumi/media/md25952272',
        'https://www.bilibili.com/bangumi/play/ep1582342',
        'https://www.bilibili.com/bangumi/media/md23432',
        'https://www.bilibili.com/bangumi/play/ep836424',
        'https://www.bilibili.com/bangumi/media/md22855584',
        'https://www.bilibili.com/bangumi/play/ep1655820',
    ]
    for u in urls:
        # bv = BiliVideoInfo.from_url(u)
        try:
            bv = create_bili_video(u, {})
            # print(f'{u} title: {bv.title} show: {bv.show()} parsed res: playinfo-{bv.playinfo is not None} | initial state-{bv.initial_state is not None} | playurl-ssr-data {bv.playurl_ssr_data is not None}')
            bv.show()
        except Exception as e:
            print(f'ex: {e}, url: {u}')


if __name__ == '__main__':
    main()