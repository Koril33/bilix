import hashlib
import hmac
import random
import time
from io import BytesIO
from pathlib import Path

import qrcode
import typer
from curl_cffi import requests as curl_requests
from qrcode.image.pure import PyPNGImage
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..config.app_config import USER_TOKEN_FILE_PATH

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:137.0) Gecko/20100101 Firefox/137.0',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Referer': 'https://www.bilibili.com/',
    'Origin': 'https://www.bilibili.com',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'Priority': 'u=0'
}

session = curl_requests.Session(headers=headers, impersonate='chrome124')


def qrcode_img():
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-fe-header&go_url=https:%2F%2Fwww.bilibili.com%2F&web_location=333.1007"
    response = session.get(url, headers=headers)
    qrcode_key = response.json()['data']['qrcode_key']
    qrcode_url = response.json()['data']['url']

    # 生成二维码图片
    qr = qrcode.make(qrcode_url, image_factory=PyPNGImage)
    buffer = BytesIO()
    qr.save(buffer)

    # 保存二维码图片到当前目录
    qr.save("login_qrcode.png")
    return qrcode_key


def get_cookie(qrcode_key):
    url = f'https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}&source=main_web&web_location=333.1228'
    while True:
        resp = session.get(url)
        resp_json = resp.json()
        code = resp_json['data']['code']
        msg = resp_json['data']['message']
        if code == 0:
            typer.echo(f'登录成功: {resp_json}')

            # 删除二维码
            Path('login_qrcode.png').unlink(missing_ok=True)
            return resp.headers.get('Set-Cookie')

        elif code == 86038:
            typer.echo(f'登陆失败: {code}, {msg}')
            raise typer.Exit(code=1)
        else:
            typer.echo(msg)
        time.sleep(2)


def dict_to_cookie_string(cookie_dict):
    return '; '.join(f'{k}={v}' for k, v in cookie_dict.items())


def generate_b_lsid():
    import time, random
    # 获取当前时间戳（毫秒）
    timestamp_ms = int(time.time() * 1000)

    # 生成 8 位随机十六进制字符串（大写，字符从 '1' 到 'F'）
    hex_chars = '123456789ABCDEF'  # 不包含 '0'
    random_hex = ''.join(random.choice(hex_chars) for _ in range(8))

    # 将时间戳转换为大写十六进制（去除 '0x' 前缀）
    timestamp_hex = hex(timestamp_ms)[2:].upper()

    # 拼接 b_lsid
    b_lsid = f"{random_hex}_{timestamp_hex}"

    return b_lsid


def generate_uuid():
    # 随机十六进制字符集（大写，1-F，不含0）
    hex_chars = '123456789ABCDEF'

    # 生成随机部分
    def r(length):
        # 生成 length 位随机十六进制字符串
        random_str = ''.join(random.choice(hex_chars) for _ in range(length))
        # 模拟 o 函数：补零（不过随机字符串长度总是够，无需补零）
        return random_str.zfill(length) if len(random_str) < length else random_str

    # 生成时间戳部分
    timestamp_mod = str(int(time.time() * 1000) % 100000)  # Date.now() % 1e5
    timestamp_str = timestamp_mod.zfill(5)  # 补齐到 5 位

    # 拼接 UUID
    uuid = (
            r(8) + "-" +
            r(4) + "-" +
            r(4) + "-" +
            r(4) + "-" +
            r(12) +
            timestamp_str +
            "infoc"
    )

    return uuid


def hmac_sha256(key, message):
    """
    使用HMAC-SHA256算法对给定的消息进行加密
    :param key: 密钥
    :param message: 要加密的消息
    :return: 加密后的哈希值
    """
    # 将密钥和消息转换为字节串
    key = key.encode('utf-8')
    message = message.encode('utf-8')

    # 创建HMAC对象，使用SHA256哈希算法
    hmac_obj = hmac.new(key, message, hashlib.sha256)

    # 计算哈希值
    hash_value = hmac_obj.digest()

    # 将哈希值转换为十六进制字符串
    hash_hex = hash_value.hex()

    return hash_hex


def gen_web_ticket():
    o = hmac_sha256("XgwSnGZ1p", f"ts{int(time.time())}")
    url = "https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket"
    params = {
        "key_id": "ec02",
        "hexsign": o,
        "context[ts]": f"{int(time.time())}",
        "csrf": ''
    }

    headers = {
        'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    }
    resp = curl_requests.post(url, params=params, headers=headers).json()
    return {
        'bili_ticket': resp['data']['ticket'],
        'bili_ticket_expires': resp['data']['created_at'] + resp['data']['ttl'],
    }


def user_login():
    qrcode_key_res = qrcode_img()
    cookie = get_cookie(qrcode_key_res)
    with open(USER_TOKEN_FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(cookie)


def user_info():
    url1 = 'https://api.bilibili.com/x/web-interface/nav'
    url3 = 'https://api.bilibili.com/x/relation/stat'
    if USER_TOKEN_FILE_PATH.is_file():
        with open(USER_TOKEN_FILE_PATH, 'r', encoding='utf-8') as f:
            headers = {
                'Cookie': f.read()
            }
    else:
        typer.echo('Token 文件不存在')
        return
    resp1 = curl_requests.get(url1, headers=headers, timeout=5)
    resp1_json = resp1.json()

    code = resp1_json['code']

    if code == 0:
        data = resp1_json['data']

        profile_picture_url = data['face']
        money = data['money']
        user_name = data['uname']
        mid = data['mid']
        level = data['level_info']['current_level']

        resp3 = curl_requests.get(url3, headers=headers, timeout=5, params={'vmid': mid})
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
        typer.echo(f'获取用户信息失败')


def user_logout():
    if USER_TOKEN_FILE_PATH.is_file():
        USER_TOKEN_FILE_PATH.unlink()
        typer.echo('退出账号成功')
    else:
        typer.echo('用户未登录, 登录请使用 --login 选项')
    return
