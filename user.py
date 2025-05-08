from curl_cffi import requests
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from log_config import app_logger


def get_user_info(headers):
    url = 'https://api.bilibili.com/x/web-interface/nav'

    resp = requests.get(url, headers=headers, timeout=5)

    code = resp.json()['code']

    if code == 0:
        data = resp.json()['data']

        profile_picture_url = data['face']
        money = data['money']
        user_name = data['uname']
        mid = data['mid']

        # 构造内容
        text = Text()
        text.append("用户名: ", style="bold cyan")
        text.append(f'{user_name}\n', style="bold green")
        text.append("用户头像 URL: ", style="bold cyan")
        text.append(f'{profile_picture_url}\n', style="bold magenta")
        text.append("硬币: ", style="bold cyan")
        text.append(f'{money}\n', style="bold red")
        text.append("mid: ", style="bold cyan")
        text.append(f'{mid}', style="bold blue")



        # 使用 Panel 包裹内容
        panel = Panel(
            text,
            title="🧐 用户信息",
            title_align="left",
            border_style="bright_blue",
            padding=(1, 2),
        )
        Console().print(panel)

    else:
        app_logger.warning(f'获取用户信息失败')
        return None