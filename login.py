import base64
from io import BytesIO
from urllib.parse import urlparse, parse_qs

import qrcode
from curl_cffi import requests
from qrcode_terminal import qrcode_terminal

from log_config import app_logger

session = requests.Session()

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
    import time
    url = f'https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}&source=main_web&web_location=333.1228'
    while True:
        resp_json = session.get(url).json()
        code = resp_json['data']['code']
        msg = resp_json['data']['message']
        if code == 0:
            app_logger.info("登录成功")

            login_success_url = resp_json['data']['url']

            parsed = urlparse(login_success_url)
            query = parse_qs(parsed.query)

            cookies = {
                'DedeUserID': query['DedeUserID'][0],
                'DedeUserID__ckMd5': query['DedeUserID__ckMd5'][0],
                'SESSDATA': query['SESSDATA'][0],
                'bili_jct': query['bili_jct'][0],
            }

            return f'SESSDATA={cookies["SESSDATA"]}'

        elif code == 86038:
            app_logger.info(msg)
            return None
        else:
            app_logger.info(msg)
        time.sleep(2)


if __name__ == '__main__':
    qrcode_key_res = qrcode_img()
    get_cookie(qrcode_key_res)