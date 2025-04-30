import logging.config

log_config_dict = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] - %(levelname)-8s :: %(message)s',
        }
    },
    'handlers': {
        'console_handler': {
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
            'formatter': 'default',
            'level': 'DEBUG',
        },
    },
    'loggers': {
        f'bilix': {
            'handlers': ['console_handler'],
            'level': 'DEBUG',
            'propagate': False,
        }
    },
    'root': {
        'handlers': ['console_handler'],
        'level': 'WARNING',
    }
}

def log_init():
    logging.config.dictConfig(log_config_dict)


app_logger = logging.getLogger('bilix')