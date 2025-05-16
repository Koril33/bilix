import json
from abc import abstractmethod

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException, HTTPError

from log_config import app_logger
from tool import clean_bili_url, sanitize_filename
import re


class BiliVideoInfo:

    playinfo_pattern = r'window\.__playinfo__\s*=\s*(\{.*?})\s*</script>'
    initial_state_pattern = r'window\.__INITIAL_STATE__\s*=\s*(\{.*?})\s*;'
    playurl_ssr_data_pattern = r'const\s+playurlSSRData\s*=\s*({.*?})\s'
    title_pattern = r'<title\b[^>]*>(.*?)</title>'

    def __init__(self, url):
        if not self.check_url_valid(url):
            raise ValueError(f"Invalid Bilibili URL: {url}")
        self.url = url
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
    def from_url(cls, url: str):
        instance = cls(url)
        instance.parse()
        return instance

    @abstractmethod
    def show(self):
        pass

    def extract(self, html_content: str):
        self.playinfo = self.extract_json(self.playinfo_pattern, html_content)
        self.initial_state = self.extract_json(self.initial_state_pattern, html_content)
        self.playurl_ssr_data = self.extract_json(self.playurl_ssr_data_pattern, html_content)

        title_match = re.search(self.title_pattern, html_content, re.IGNORECASE | re.DOTALL)
        if title_match:
            self.title = sanitize_filename(title_match.group(1).strip())

    def parse(self):
        try:
            resp = requests.get(self.url, timeout=5)
            resp.raise_for_status()
            self.extract(resp.text)
        except HTTPError:
            app_logger.exception(f'HTTP error')
        except RequestException:
            app_logger.exception(f'Request error')



class BiliNormalVideo(BiliVideoInfo):
    def __init__(self, url):
        super().__init__(url)
        self.parse()

    def show(self):
        return "普通视频"


class BiliMultiPartVideo(BiliVideoInfo):
    def __init__(self, url):
        super().__init__(url)
        self.parse()

    def show(self):
        return "多集视频"


class BiliMovie(BiliVideoInfo):
    def __init__(self, url):
        super().__init__(url)
        self.parse()

    def show(self):
        return "电影"


class BiliBangumi(BiliVideoInfo):

    def __init__(self, url):
        super().__init__(url)
        self.parse()

    def show(self):
        return "番剧"


def create_bili_video(url: str) -> BiliVideoInfo:
    clean_url = clean_bili_url(url)
    if 'video/BV' in clean_url:
        bv = BiliVideoInfo.from_url(clean_url)
        if len(bv.initial_state['videoData']['pages']) > 1:
            return BiliMultiPartVideo(url)
        return BiliNormalVideo(url)
    elif '/bangumi/media/md' in clean_url:
        return BiliMovie(url)
    elif '/bangumi/play/' in clean_url:
        return BiliBangumi(url)
    else:
        raise ValueError(f"Unsupported Bilibili URL: {url}")


def main():
    urls = [
        # 'https://www.bilibili.com/video/BV1yt4y1Q7SS/',
        # 'https://www.bilibili.com/video/BV12R4y1J75d',
        # 'https://www.bilibili.com/bangumi/play/ep1656974',
        # 'https://www.bilibili.com/bangumi/play/ss12548',
        'https://www.bilibili.com/bangumi/media/md80952',
    ]
    for u in urls:
        # bv = BiliVideoInfo.from_url(u)
        bv = create_bili_video(u)
        print(f'{u} title: {bv.title} show: {bv.show()} parsed res: playinfo-{bv.playinfo is not None} | initial state-{bv.initial_state is not None} | playurl-ssr-data {bv.playurl_ssr_data is not None}')

if __name__ == '__main__':
    main()