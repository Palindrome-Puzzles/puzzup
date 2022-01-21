from settings.base import *  # pylint: disable=unused-wildcard-import,wildcard-import

from decouple import config

HUNT_REPO = config('HUNT_REPO')

DEBUG = True

EMAIL_SUBJECT_PREFIX = u"[DEVELOPMENT] "

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

INTERNAL_IPS = [
    'localhost',
    '127.0.0.1',
]
if not SITE_PASSWORD:
    SITE_PASSWORD = "racecar"

INSTALLED_APPS.append("debug_toolbar")
MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware')

ALLOWED_HOSTS = ['localhost']

DATABASES = {'default': dj_database_url.config(default='postgres://localhost:5432/puzzup')}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "django-file": {
            "format": "%(asctime)s [%(levelname)s] %(module)s\n%(message)s"
        },
        "puzzles-file": {"format": "%(asctime)s [%(levelname)s] %(message)s"},
        "django-console": {
            "format": "\033[34;1m%(asctime)s \033[35;1m[%(levelname)s] \033[34;1m%(module)s\033[0m\n%(message)s"
        },
        "puzzles-console": {
            "format": "\033[36;1m%(asctime)s \033[35;1m[%(levelname)s] \033[36;1m%(name)s\033[0m %(message)s"
        },
    },
    "handlers": {
        "django": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": "./logs/django.log",
            "formatter": "django-file",
        },
        "puzzle": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": "./logs/puzzle.log",
            "formatter": "puzzles-file",
        },
        "request": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": "./logs/request.log",
            "formatter": "puzzles-file",
        },
        "django-console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "django-console",
        },
        "puzzles-console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "puzzles-console",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["django", "django-console"],
            "level": "DEBUG",
            "propagate": True,
        },
        "django.db.backends": {
            "level": "DEBUG",
            "handlers": ["django"],
            "propagate": False,
        },
        "django.server": {
            "level": "DEBUG",
            "handlers": ["django"],
            "propagate": False,
        },
        "django.utils.autoreload": {"level": "INFO", "propagate": True,},
        "puzzles": {
            "handlers": ["puzzles-console"],
            "level": "DEBUG",
            "propagate": True,
        },
        "puzzles.puzzle": {
            "handlers": ["puzzle", "puzzles-console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "puzzles.request": {
            "handlers": ["request", "puzzles-console"],
            "level": "DEBUG",
            "propagate": False,
        },
        "puzzle_editing.commands": {
            "handlers": ["puzzles-console", "django"],
            "level": "DEBUG",
        },
    },
}

# Allow for local (per-user) override
try:
    from settings_local import *  # pylint: disable=wildcard-import
except ImportError:
    pass
