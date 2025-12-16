import tomllib

from platformdirs import user_config_path, user_downloads_path

USER_CONFIG_DIR_PATH = user_config_path(appname='djhx-bilix', appauthor='djhx')
USER_DOWNLOAD_DIR_PATH = user_downloads_path() / 'djhx-bilix'

USER_CONFIG_FILE_PATH = USER_CONFIG_DIR_PATH / 'config.toml'
USER_TOKEN_FILE_PATH = USER_CONFIG_DIR_PATH / 'token.txt'

USER_CONFIG_DIR_PATH.mkdir(parents=True, exist_ok=True)
USER_DOWNLOAD_DIR_PATH.mkdir(parents=True, exist_ok=True)

def read_config() -> dict:
    if USER_CONFIG_FILE_PATH.is_file():
        try:
            with open(USER_CONFIG_FILE_PATH, 'rb') as f:
                return tomllib.load(f)
        except Exception as e:
            return {}
    return {}