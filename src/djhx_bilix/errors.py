"""Errors safe to display to an end user (never include response bodies or cookies)."""


class BilixError(Exception):
    """An actionable download, configuration or account error."""


class InputError(BilixError):
    """Invalid user input."""


class NetworkError(BilixError):
    """A request or a stream transfer failed."""


class MediaError(BilixError):
    """Media validation or muxing failed."""


class DownloadError(BilixError):
    """A download failed; its work directory is retained for inspection."""


class APIError(BilixError):
    """A numeric upstream status with a safe, locally defined message."""

    def __init__(self, code: int):
        self.code = code
        message = {
            -101: "登录凭据已失效，请使用 blx auth login 重新扫码",
            -10403: "该内容受账号权限、地区或版权限制",
            -404: "视频或接口资源不存在",
            -403: "请求被服务器拒绝，请稍后重试",
            -412: "请求受到临时风控限制，请稍后重试",
        }.get(code, f"Bilibili 接口返回错误（代码 {code}）")
        super().__init__(message)
