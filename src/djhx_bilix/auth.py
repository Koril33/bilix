"""QR login and local credential storage; credentials never enter terminal output."""

import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path

import qrcode
from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException
from qrcode.image.pure import PyPNGImage

from .bilibili.client import USER_AGENT, BilibiliClient
from .config import Settings
from .credentials import normalize_cookie
from .errors import APIError, BilixError, NetworkError, OperationCancelled
from .operations import CancellationToken


@dataclass(frozen=True)
class LoginEvent:
    """QR login state. QR image bytes are deliberately omitted from repr/logs."""

    state: str
    qr_image: bytes | None = field(default=None, repr=False)


def response_cookie(response) -> str:
    """Use the cookie jar; never store Set-Cookie attributes as a Cookie header."""
    cookies = response.cookies.get_dict()
    if not cookies:
        for header in response.headers.get_list("Set-Cookie"):
            parsed = SimpleCookie()
            parsed.load(header)
            cookies.update({key: value.value for key, value in parsed.items()})
    if not cookies.get("SESSDATA"):
        raise BilixError("登录响应缺少 SESSDATA，请重新扫码")
    return normalize_cookie(
        "; ".join(f"{name}={value}" for name, value in cookies.items()), require_session=True
    )


def save_token(settings: Settings, cookie: str) -> None:
    cookie = normalize_cookie(cookie, require_session=True)
    settings.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=".token-", dir=settings.config_dir)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(cookie)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, settings.token_file)
    finally:
        temporary.unlink(missing_ok=True)


def login(
    settings: Settings,
    notify: Callable[[str], None],
    *,
    cancel: CancellationToken | None = None,
    event: Callable[[LoginEvent], None] | None = None,
) -> None:
    if cancel:
        cancel.raise_if_cancelled()
    settings.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix="login-", suffix=".png", dir=settings.config_dir)
    os.close(descriptor)
    image_path = Path(name)
    try:
        with requests.Session(headers={"User-Agent": USER_AGENT}, impersonate="chrome") as session:
            if cancel:
                cancel.raise_if_cancelled()
            response = session.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate", timeout=15
            )
            if cancel:
                cancel.raise_if_cancelled()
            response.raise_for_status()
            data = response.json().get("data") or {}
            if not data.get("url") or not data.get("qrcode_key"):
                raise BilixError("无法生成登录二维码")
            with image_path.open("wb") as image:
                qrcode.make(data["url"], image_factory=PyPNGImage).save(image)
            notify(f"请使用哔哩哔哩手机 App 扫码：{image_path}")
            if event:
                event(LoginEvent("qr_ready", image_path.read_bytes()))
            deadline = time.monotonic() + 180
            scanned = False
            while time.monotonic() < deadline:
                if cancel:
                    cancel.raise_if_cancelled()
                response = session.get(
                    "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                    params={"qrcode_key": data["qrcode_key"]},
                    timeout=15,
                )
                if cancel:
                    cancel.raise_if_cancelled()
                response.raise_for_status()
                state = response.json().get("data") or {}
                code = state.get("code")
                if code == 0:
                    save_token(settings, response_cookie(response))
                    notify("登录成功，凭据已保存在用户配置目录")
                    if event:
                        event(LoginEvent("success"))
                    return
                if code == 86038:
                    if event:
                        event(LoginEvent("expired"))
                    raise BilixError("二维码已过期，请重新执行 blx auth login")
                if code == 86090 and not scanned:
                    notify("已扫码，请在手机上确认登录")
                    if event:
                        event(LoginEvent("scanned"))
                    scanned = True
                elif code not in (86101, 86090):
                    raise BilixError("登录接口返回未知状态，请重新扫码")
                if cancel:
                    if cancel.wait(2):
                        cancel.raise_if_cancelled()
                else:
                    time.sleep(2)
        if cancel:
            cancel.raise_if_cancelled()
        if event:
            event(LoginEvent("expired"))
        raise BilixError("等待扫码超过 3 分钟，请重试")
    except OperationCancelled:
        if event:
            event(LoginEvent("cancelled"))
        raise
    except (RequestException, ValueError):
        if cancel and cancel.cancelled():
            if event:
                event(LoginEvent("cancelled"))
            raise OperationCancelled("操作已取消") from None
        raise NetworkError("登录请求失败，请检查网络后重试") from None
    finally:
        image_path.unlink(missing_ok=True)


def status(client: BilibiliClient) -> dict:
    if not client.settings.token_file.is_file():
        return {"logged_in": False}
    try:
        data = client.api("x/web-interface/nav")
    except APIError as error:
        if error.code == -101:
            return {"logged_in": False, "expired": True}
        raise
    vip = data.get("vip") or {}
    return {
        "logged_in": bool(data.get("isLogin")),
        "name": data.get("uname", ""),
        "uid": data.get("mid"),
        "level": (data.get("level_info") or {}).get("current_level"),
        "vip": vip.get("status") == 1,
        "vip_type": vip.get("type", 0),
        "vip_expires_at": vip.get("due_date", 0),
        "coins": data.get("money"),
    }


def logout(settings: Settings) -> None:
    settings.token_file.unlink(missing_ok=True)
