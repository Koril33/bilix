"""Update handoff and fixed installation actions, dispatched before importing Qt."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from djhx_bilix import __version__

from .client import (
    BUNDLE_NAMES,
    LINUX_EXECUTABLE,
    PACKAGE,
    Distribution,
    PreparedUpdate,
    atomic_json,
    installed_deb_version,
    installer_location,
    update_cache,
)
from .processes import current_processes, other_instances, wait_for_exit
from .protocol import ASSETS, MAX_METADATA, UpdateError, read_json, sha256, verify_bundle, version

ROOT_STAGING = Path("/var/cache/djhx-bilix-gui-updater")


def require_root_owned(path: Path, *, directory=False) -> None:
    info = path.lstat()
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not expected or info.st_uid != 0 or info.st_mode & 0o022:
        raise UpdateError("root 更新文件或暂存目录权限不安全")


def snapshot_bundle(directory: Path) -> dict[str, bytes]:
    blobs = {}
    for name in BUNDLE_NAMES:
        descriptor = os.open(
            directory / name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_METADATA:
                raise UpdateError("缓存元数据不是有界普通文件")
            blobs[name] = stream.read(MAX_METADATA + 1)
    return blobs


def backup_preferences(config: Path, transaction: Path) -> None:
    backup = transaction / "config-backup"
    backup.mkdir(mode=0o700)
    for name in ("config.toml", "gui.ini"):
        source = config / name
        if source.is_file():
            shutil.copy2(source, backup / name)
    # token.txt is deliberately not copied or migrated by the updater.


def handoff(prepared: PreparedUpdate, identity: Distribution, config: Path) -> Path:
    prepared.revalidate()
    processes = current_processes(identity.executable)
    if other_instances(identity.executable, exclude={p["pid"] for p in processes}):
        raise UpdateError("同一路径有其他 BiliX 实例，请先关闭后再更新")
    if identity.kind == "portable":
        if identity.executable.suffix.lower() != ".exe":
            raise UpdateError("绿色版更新目标不是 EXE")
        # Test real directory writes, not os.access (Windows ACLs may differ).
        with tempfile.TemporaryFile(dir=identity.executable.parent):
            pass
    elif identity.kind == "installer":
        if identity.executable != installer_location() / "runtime" / "BiliX-GUI.exe":
            raise UpdateError("安装身份改变，请手动运行安装器")
    elif shutil.which("pkexec") is None:
        raise UpdateError("系统缺少 pkexec，请安装 polkit 或手动 apt install 已下载的 deb")
    transactions = update_cache() / "transactions"
    transactions.mkdir(parents=True, exist_ok=True, mode=0o700)
    transaction = transactions / uuid.uuid4().hex
    transaction.mkdir(mode=0o700)
    backup_preferences(config, transaction)
    helper_root = transaction / "helper"
    if identity.kind == "portable":
        helper_root.mkdir()
        helper = helper_root / "BiliX-Update.exe"
        shutil.copy2(identity.executable, helper)
    else:
        # A standalone EXE cannot be copied without its DLLs. Copy the existing runtime
        # outside the directory that Inno/dpkg will replace, keeping the helper independent.
        if (
            shutil.disk_usage(transaction).free
            < sum(p.stat().st_size for p in identity.executable.parent.rglob("*") if p.is_file())
            + 100 * 1024**2
        ):
            raise UpdateError("没有足够空间准备独立更新协调器")
        shutil.copytree(identity.executable.parent, helper_root)
        helper = helper_root / identity.executable.name
    request = {
        "schema": 1,
        "artifact_id": identity.artifact_id,
        "directory": str(prepared.directory),
        "target": str(identity.executable),
        "old_sha256": sha256(identity.executable),
        "version": prepared.artifact.version,
        "processes": processes,
    }
    atomic_json(transaction / "request.json", request)
    options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if sys.platform == "win32"
        else {
            "start_new_session": True,
        }
    )
    with (transaction / "helper.log").open("wb") as log:
        process = subprocess.Popen(
            [str(helper), "--apply-update", str(transaction)],
            cwd=helper_root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            **options,
        )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if (transaction / "accepted.json").exists():
            return transaction
        if process.poll() is not None:
            result = transaction / "result.json"
            message = read_json(result.read_bytes()).get("message") if result.exists() else ""
            raise UpdateError(message or "独立更新协调器无法启动，当前应用继续运行")
        time.sleep(0.1)
    atomic_json(transaction / "abort.json", {"abort": True})
    raise UpdateError("更新协调器未就绪，当前应用继续运行；请查看 helper.log")


def portable_replace(
    prepared: PreparedUpdate, target: Path, old_hash: str, transaction: Path
) -> Path:
    """Keep the previous successful backup until the new executable starts successfully."""
    prepared.revalidate()
    if sha256(target) != old_hash:
        raise UpdateError("绿色版原 EXE 在准备后改变，拒绝覆盖")
    temporary = target.with_name(target.name + ".new-" + transaction.name)
    backup = target.with_name(target.name + ".previous-" + transaction.name)
    try:
        shutil.copy2(prepared.package, temporary)
        prepared.artifact.verify_file(temporary)
        os.replace(target, backup)
        try:
            os.replace(temporary, target)
        except OSError:
            os.replace(backup, target)
            raise
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def startup_result(transaction: Path) -> None:
    """Called by the ordinary user's GUI after creating and showing its main window."""
    if transaction.parent.resolve() != (update_cache() / "transactions").resolve():
        raise UpdateError("更新启动记录目录不合法")
    request = read_json((transaction / "request.json").read_bytes())
    if request.get("version") == __version__:
        atomic_json(transaction / "startup.json", {"version": __version__, "pid": os.getpid()})


def restart(target: Path, transaction: Path, expected_version: str) -> bool:
    try:
        process = subprocess.Popen(
            [str(target), "--updated", str(transaction)],
            cwd=target.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        # An invalid executable or missing loader is also a startup failure.
        # Return through the same recovery path as an early process exit.
        return False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        marker = transaction / "startup.json"
        if marker.exists() and read_json(marker.read_bytes()).get("version") == expected_version:
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def _message(text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "BiliX 更新", 0x10)
    elif shutil.which("notify-send"):
        subprocess.run(["notify-send", "BiliX 更新", text], check=False, timeout=10)


def apply_update(transaction: Path) -> int:
    backup = None
    installed = False
    target = None
    kind = ""
    lock_descriptor = None
    lock_path = None
    exited = False
    accepted = False
    try:
        request = read_json((transaction / "request.json").read_bytes())
        if request.get("schema") != 1:
            raise UpdateError("更新事务格式不支持")
        directory = Path(request["directory"]).resolve()
        _, artifact = verify_bundle(snapshot_bundle(directory), request["artifact_id"])
        prepared = PreparedUpdate(artifact, directory)
        prepared.revalidate()
        if artifact.version != request["version"] or version(artifact.version) < version(
            __version__
        ):
            raise UpdateError("更新目标倒退或事务版本不匹配")
        kind = Distribution(artifact.artifact_id, Path(request["target"])).kind
        target = Path(request["target"]).resolve()
        if kind == "installer" and target != installer_location() / "runtime" / "BiliX-GUI.exe":
            raise UpdateError("安装器更新目标与当前用户记录不一致")
        if kind == "deb" and target != LINUX_EXECUTABLE:
            raise UpdateError("deb 更新仅支持固定系统安装位置")
        if kind == "portable" and target.suffix.lower() != ".exe":
            raise UpdateError("绿色版目标不是 EXE")
        lock_path = (
            target.with_name(target.name + ".update-lock")
            if kind == "portable"
            else (transaction.parent / (artifact.artifact_id + ".lock"))
        )
        # Exclusive creation is intentionally simple; interrupted locks require manual review.
        lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(lock_descriptor, str(os.getpid()).encode("ascii"))
        atomic_json(transaction / "accepted.json", {"accepted": True})
        accepted = True
        wait_for_exit(request["processes"], abort=transaction / "abort.json")
        exited = True
        if (transaction / "abort.json").exists():
            raise UpdateError("更新交接已取消")
        if other_instances(target):
            raise UpdateError("其他 BiliX 实例仍在使用此安装，请关闭后重试")
        prepared.revalidate()
        if kind == "portable":
            backup = portable_replace(prepared, target, request["old_sha256"], transaction)
            installed = True
        elif kind == "installer":
            # Keep the wizard; only this coordinator restarts the application.
            result = subprocess.run(
                [
                    str(prepared.package),
                    "/BILIXUPDATE",
                    "/NORESTART",
                    "/RESTARTEXITCODE=3010",
                    f"/LOG={transaction / 'install.log'}",
                    f"/DIR={target.parent.parent}",
                ],
                check=False,
            )
            if result.returncode == 3010:
                installed = True
                raise UpdateError(
                    "安装器要求系统重启；请保存工作并手动重启，BiliX 不会自动重启系统"
                )
            if result.returncode:
                raise UpdateError(
                    f"安装未完成（Inno 返回 {result.returncode}），请查看 install.log"
                )
            installed = True
        else:
            result = subprocess.run(
                [
                    "/usr/bin/pkexec",
                    "--disable-internal-agent",
                    str(LINUX_EXECUTABLE),
                    "--install-deb",
                    str(directory),
                ],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
            (transaction / "install.log").write_text(
                result.stdout + result.stderr, encoding="utf-8"
            )
            if result.returncode in (126, 127):
                raise UpdateError("系统授权已取消或不可用；更新包保留，可手动 apt install")
            if result.returncode:
                raise UpdateError("APT 安装未完成，请查看 install.log；必要时手动修复包管理器")
            installed = True
        if not restart(target, transaction, artifact.version):
            if backup is not None and not other_instances(target):
                os.replace(backup, target)
                backup = None
                installed = False
                raise UpdateError("新版启动失败，已恢复上一 EXE；关闭此提示后重新打开")
            hint = f"；上一 EXE 在 {backup}" if backup else "；请手动恢复上版或检查诊断"
            raise UpdateError("安装已完成，但未收到新版启动结果" + hint)
        if backup is not None:
            os.replace(backup, target.with_name(target.name + ".previous.exe"))
        atomic_json(transaction / "result.json", {"status": "success", "version": artifact.version})
        return 0
    except (UpdateError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        atomic_json(
            transaction / "result.json",
            {"status": "failed", "installed": installed, "message": str(exc)},
        )
        # Once handoff was accepted the GUI may already have closed. Report wait
        # failures too; previously these left only a cache file and no visible result.
        if accepted and not (transaction / "abort.json").exists():
            _message(str(exc) + f"\n更新记录：{transaction}")
            if (
                exited
                and not installed
                and target is not None
                and target.is_file()
                and not other_instances(target)
            ):
                subprocess.Popen([str(target)], cwd=target.parent)
        return 1
    finally:
        if lock_descriptor is not None:
            os.close(lock_descriptor)
            lock_path.unlink(missing_ok=True)


def root_install_deb(directory: Path) -> int:
    """The packaged, root-owned entry point accepts a cache directory, never a command."""
    if (
        sys.platform != "linux"
        or os.geteuid() != 0
        or Path(sys.argv[0]).resolve() != LINUX_EXECUTABLE
    ):
        raise UpdateError("deb 安装入口只能通过系统安装的固定 helper 提权执行")
    require_root_owned(LINUX_EXECUTABLE)
    require_root_owned(ASSETS / "update-keys.json")
    # Authenticate metadata from the user's writable cache before any privileged install.
    _, artifact = verify_bundle(snapshot_bundle(directory), "linux-amd64-deb")
    current = installed_deb_version()
    if (
        subprocess.run(
            ["/usr/bin/dpkg", "--compare-versions", artifact.package_version, "gt", current],
            check=False,
        ).returncode
        != 0
    ):
        raise UpdateError("APT 安装拒绝相同版本或降级")
    staging_root = ROOT_STAGING
    staging_root.mkdir(mode=0o755, exist_ok=True)
    require_root_owned(staging_root, directory=True)
    with tempfile.TemporaryDirectory(prefix="install-", dir=staging_root) as raw_stage:
        stage = Path(raw_stage)
        stage.chmod(0o755)  # _apt may read public artifacts, but cannot modify them.
        package = stage / artifact.filename
        source = directory / artifact.filename
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream, package.open("xb") as destination:
            source_info = os.fstat(stream.fileno())
            if not stat.S_ISREG(source_info.st_mode) or source_info.st_size != artifact.size:
                raise UpdateError("deb 缓存不是匹配大小的普通文件")
            remaining = artifact.size
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    raise UpdateError("deb 缓存在复制时改变")
                destination.write(block)
                remaining -= len(block)
        package.chmod(0o644)
        # Verify the root-controlled copy, eliminating cache tampering between check/install.
        artifact.verify_file(package)
        fields = subprocess.run(
            [
                "/usr/bin/dpkg-deb",
                "--show",
                "--showformat=${Package} ${Version} ${Architecture}",
                str(package),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.split()
        if fields != [PACKAGE, artifact.package_version, "amd64"]:
            raise UpdateError("deb 内部包名、版本或架构不匹配签名清单")
        result = subprocess.run(
            [
                "/usr/bin/apt-get",
                "-y",
                "--no-remove",
                "-o",
                "Dpkg::Use-Pty=0",
                "-o",
                "DPkg::Lock::Timeout=30",
                "install",
                str(package),
            ],
            check=False,
        )
        if result.returncode or installed_deb_version() != artifact.package_version:
            raise UpdateError("APT 未完成目标版本安装，请检查输出和包管理器状态")
    return 0


def dispatch(arguments: list[str]) -> int:
    try:
        if len(arguments) != 2:
            raise UpdateError("更新内部入口参数不合法")
        if arguments[0] == "--apply-update":
            return apply_update(Path(arguments[1]).resolve())
        if arguments[0] == "--install-deb":
            return root_install_deb(Path(arguments[1]).resolve())
        raise UpdateError("未知更新内部入口")
    except (UpdateError, OSError, subprocess.SubprocessError) as exc:
        if sys.stderr is not None:
            print(str(exc), file=sys.stderr)
        return 1
