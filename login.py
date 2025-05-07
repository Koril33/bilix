import base64
import hashlib
import hmac
import math
import random
import time
import uuid
from io import BytesIO

import qrcode
from curl_cffi import requests

from log_config import app_logger

session = requests.Session()

def dict_to_cookie_string(cookie_dict):
    return '; '.join(f'{k}={v}' for k, v in cookie_dict.items())


def qrcode_img():
    url = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate?source=main-fe-header&go_url=https:%2F%2Fwww.bilibili.com%2F&web_location=333.1007"

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

    response = session.get(url, headers=headers, impersonate='chrome124')
    qrcode_key = response.json()['data']['qrcode_key']
    qrcode_url = response.json()['data']['url']

    # 生成二维码图片
    qr = qrcode.make(qrcode_url)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    # 命令行上显示 qrcode
    # qrcode_terminal.draw(qrcode_url)

    # 保存二维码图片到当前目录
    qr.save("login_qrcode.png")
    app_logger.info("登陆二维码存储到当前目录下: login_qrcode.png, 请扫码登录")

    # 编码成 base64
    img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    img_base64_url = f"data:image/png;base64,{img_base64}"
    app_logger.info(f'Base64 编码的 qrcode: {img_base64_url}')

    return qrcode_key


def get_cookie(qrcode_key):
    url = f'https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}&source=main_web&web_location=333.1228'
    while True:
        resp_json = session.get(url).json()
        code = resp_json['data']['code']
        msg = resp_json['data']['message']
        if code == 0:
            app_logger.info("登录成功")

            first_req = session.get('https://bilibili.com/')
            cookies_dict = first_req.cookies.get_dict()
            app_logger.info(f'cookies dict: {cookies_dict}')

            buvid4 = session.get("https://api.bilibili.com/x/frontend/finger/spi").json()["data"]["b_4"]
            app_logger.info(f'buvid4: {buvid4}')
            cookies_dict['buvid4'] = buvid4
            cookies_dict['header_theme_version'] = 'CLOSE'
            cookies_dict['enable_web_push'] = 'DISABLE'
            cookies_dict['buvid_fp_plain'] = 'undefined'
            cookies_dict['hit-dyn-v2'] = 1
            cookies_dict['enable_feed_channel'] = 'ENABLE'
            cookies_dict['share_source_origin'] = 'WEIXIN'
            cookies_dict['CURRENT_QUALITY'] = 0
            cookies_dict['bsource'] = 'search_bing'
            cookies_dict['home_feed_column'] = 5

            web_ticket_dict = gen_web_ticket()
            cookies_dict['bili_ticket'] = web_ticket_dict['bili_ticket']
            cookies_dict['bili_ticket_expires'] = web_ticket_dict['bili_ticket_expires']

            cookies_dict['browser_resolution'] = '2040-410'


            cookies_dict['CURRENT_FNVAL'] = 4048

            cookies_dict['b_lsid'] = generate_b_lsid()
            cookies_dict['_uuid'] = generate_uuid()

            return dict_to_cookie_string(cookies_dict)

        elif code == 86038:
            app_logger.info(msg)
            return None
        else:
            app_logger.info(msg)
        time.sleep(2)


def b_lsid():
    t = ""
    for _ in range(8):
        t += hex(math.ceil(16 * random.uniform(0, 1)))[2:].upper()
    result = t.rjust(8, "0")
    times = int(time.time() * 1000)
    result2 = hex(times)[2:].upper()
    return result + "_" + result2


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


def gen_uuid():
    uuid_sec = str(uuid.uuid4())
    time_sec = str(int(time.time() * 1000 % 1e5))
    time_sec = time_sec.rjust(5, "0")
    return f"{uuid_sec}{time_sec}infoc"



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
    resp = requests.post(url, params=params, headers=headers).json()
    return {
        'bili_ticket': resp['data']['ticket'],
        'bili_ticket_expires': resp['data']['created_at'] + resp['data']['ttl'],
    }



if __name__ == '__main__':
    res = gen_web_ticket()
    print(res)