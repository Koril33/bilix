import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from curl_cffi import requests
from rich.progress import Progress, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn, TimeElapsedColumn, \
    FileSizeColumn, TotalFileSizeColumn, SpinnerColumn, TransferSpeedColumn

from download_sync import download_stream
from log_config import app_logger

update_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0',
}

TEMP_UPDATE_ZIP_NAME = 'temp_bilix_update.zip'
TEMP_UPDATE_DIR_NAME = 'temp_bilix_update'

def version_tuple(v):
    return tuple(map(int, v.strip("v").split(".")))

def is_newer_version(current, latest):
    return version_tuple(latest) > version_tuple(current)

def check_update(current_version):
    gitee_repo_owner = "ding_jing_hui"
    github_repo_owner = 'Koril33'
    repo_name = "bilix"

    github_url = f"https://api.github.com/repos/{github_repo_owner}/{repo_name}/releases/latest"
    gitee_url = f"https://gitee.com/api/v5/repos/{gitee_repo_owner}/{repo_name}/releases/latest"

    try:
        response = requests.get(url=github_url, headers=update_headers)
        response.raise_for_status()
        latest_release = response.json()
        latest_version = latest_release['tag_name'].lstrip('v')

        if is_newer_version(current=current_version, latest=latest_version):
            return latest_release
        return None
    except Exception as e:
        app_logger.error(f"检查更新失败: {e}")
        return None


def download_latest_zip(latest_zip_url, zip_name):
    with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            TimeElapsedColumn(),
            FileSizeColumn(),
            TotalFileSizeColumn(),
            SpinnerColumn(),
            TransferSpeedColumn(),
    ) as progress:
        download_stream(latest_zip_url, update_headers, zip_name, progress)

def extract_zip(zip_path):
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.testzip()
            temp_dir = Path(TEMP_UPDATE_DIR_NAME)
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            temp_dir.mkdir()
            zip_ref.extractall(temp_dir)

    except zipfile.BadZipFile:
        app_logger.error("下载的文件不是有效的 zip 文件。")
    except Exception as e:
        app_logger.error(f"解压和替换文件时发生错误: {e}")


def replace_exe(current_exe, latest_exe):
    bat_content = f"""@echo off
timeout /t 2 /nobreak > nul
echo 正在删除旧版本...
del "{current_exe}"
echo 移动新版本...
move "{latest_exe}" "{current_exe}"
echo 清理临时文件...
rmdir /S /Q "{TEMP_UPDATE_DIR_NAME}"
del /Q "{TEMP_UPDATE_ZIP_NAME}"
echo 删除自身...
del "%~f0"
"""

    bat_path = "update.bat"
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(bat_content)

    subprocess.Popen(
        ["cmd.exe", "/C", bat_path],
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    app_logger.info("更新完毕")
    sys.exit(0)

def update_exe(current_version):
    res = check_update(current_version)
    if not res:
        app_logger.info("无需更新, 已是最新版本")
        return

    app_logger.info(f"检索到新版本, 开始更新: {current_version} -> {res['tag_name']}")
    res_url = res['assets'][0].get('browser_download_url')
    download_latest_zip(res_url, TEMP_UPDATE_ZIP_NAME)
    extract_zip(TEMP_UPDATE_ZIP_NAME)
    replace_exe('bilix.exe', f'{TEMP_UPDATE_DIR_NAME}\\bilix.exe')
