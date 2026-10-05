"""Errors safe to display to an end user (never include response bodies or cookies)."""


class BilixError(Exception):
    """An actionable download, configuration or account error."""

    error_code = "unknown"
    action = "请检查设置，运行 blx doctor 后重试"

    def __init__(self, message: str, *, error_code: str | None = None, action: str | None = None):
        super().__init__(message)
        self.error_code = error_code or type(self).error_code
        self.action = action if action is not None else type(self).action


class InputError(BilixError):
    """Invalid user input."""

    error_code = "input"
    action = "请检查输入、选集及媒体选项"


class NetworkError(BilixError):
    """A request or a stream transfer failed."""

    error_code = "network"
    action = "请检查网络，稍后重试"


class SelectionError(InputError):
    """Valid options that the current media or account cannot satisfy."""

    error_code = "media_selection"
    action = "请调整画质、编码或音轨，并检查账号权限"


class MediaError(BilixError):
    """Media validation or muxing failed."""

    error_code = "validation"
    action = "请运行诊断，检查 FFmpeg 与剩余空间"


class DownloadError(BilixError):
    """A download failed; its work directory is retained for inspection."""

    error_code = "filesystem"
    action = "请检查保存路径、权限和剩余空间"

    def __init__(self, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        if isinstance(cause, BilixError):
            self.error_code, self.action = cause.error_code, cause.action


class OperationCancelled(BilixError):
    """The user cancelled an operation before its result was committed."""

    error_code = "canceled"
    action = ""


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
        self.error_code, self.action = {
            -101: ("auth_expired", "请重新扫码登录"),
            -10403: ("access", "请检查账号、购买权限和地区限制"),
            -404: ("source_missing", "请检查视频是否仍可访问"),
            -403: ("network", "请稍后重试"),
            -412: ("network", "请稍后重试"),
        }.get(code, ("api", "请检查账号和网络"))


def safe_error(error: Exception) -> tuple[str, str, str]:
    """Only our domain exceptions have displayable text; never inspect third-party text."""
    if isinstance(error, BilixError):
        return str(error), error.error_code, error.action
    if isinstance(error, (OSError, UnicodeError)):
        return "文件或目录无法访问", "filesystem", "请检查路径、权限和剩余空间"
    return "操作失败", "unknown", "请检查网络和设置，运行 blx doctor"
