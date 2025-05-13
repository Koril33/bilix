from curl_cffi import requests
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from log_config import app_logger


def get_user_info(headers):
    url1 = 'https://api.bilibili.com/x/web-interface/nav'
    # url2 = 'https://api.bilibili.com/x/space/myinfo'
    url3 = 'https://api.bilibili.com/x/relation/stat'
    resp1 = requests.get(url1, headers=headers, timeout=5)
    resp1_json = resp1.json()
    # resp2 = requests.get(url2, headers=headers, timeout=5)
    # resp2_json = resp2.json()

    code = resp1_json['code']

    if code == 0:
        data = resp1_json['data']

        profile_picture_url = data['face']
        money = data['money']
        user_name = data['uname']
        mid = data['mid']
        level = data['level_info']['current_level']

        resp3 = requests.get(url3, headers=headers, timeout=5, params={'vmid': mid})
        resp3_json = resp3.json()

        # 构造内容
        text = Text()
        text.append("mid: ", style="bold cyan")
        text.append(f'{mid}\n', style="bold blue")
        text.append("用户名: ", style="bold cyan")
        text.append(f'{user_name}\n', style="bold green")
        text.append("用户头像 URL: ", style="bold cyan")
        text.append(f'{profile_picture_url}\n', style="bold magenta")
        text.append("硬币: ", style="bold cyan")
        text.append(f'{money}\n', style="bold red")
        text.append(f'等级: ', style="bold cyan")
        text.append(f'{level}\n', style="bold red")
        text.append(f'关注数: ', style="bold cyan")
        text.append(f'{resp3_json["data"]["following"]}\n')
        text.append(f'粉丝数: ', style="bold cyan")
        text.append(f'{resp3_json["data"]["follower"]}\n')

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