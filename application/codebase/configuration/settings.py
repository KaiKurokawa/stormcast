"""
---------------------------------------------------------------------------
Настройки приложения
---------------------------------------------------------------------------

Назначение:
    Центральная конфигурация Django-проекта. Параметры, различающиеся
    между окружениями, читаются из переменных окружения.

Стек:
    Django 6.1, Django REST Framework, drf-spectacular, PostgreSQL.
"""

from pathlib import Path

from configuration.environment import (
    read_boolean_variable,
    read_integer_variable,
    read_list_variable,
    read_required_text,
    read_text,
)


# -------------------------------------------------------------------------
# Корневой каталог
# -------------------------------------------------------------------------

BASE_DIRECTORY = Path(__file__).resolve().parent.parent

APPLICATION_NAME = "Шторм"
APPLICATION_TITLE = "Система метеорологических рассылок"
API_VERSION = "v1"


# -------------------------------------------------------------------------
# Основные настройки
# -------------------------------------------------------------------------

SECRET_KEY = read_required_text("APPLICATION_SECRET_KEY")

DEBUG = read_boolean_variable("APPLICATION_DEBUG_MODE", False)

ALLOWED_HOSTS = read_list_variable(
    "APPLICATION_ALLOWED_HOSTS",
    "localhost,127.0.0.1",
)

# Обязательный параметр Django 4+ для работы CSRF за reverse-proxy.
CSRF_TRUSTED_ORIGINS = read_list_variable("APPLICATION_CSRF_TRUSTED_ORIGINS")


# -------------------------------------------------------------------------
# Признаки возможностей
# -------------------------------------------------------------------------

APPLICATION_FEATURE_ENABLE_API = read_boolean_variable(
    "APPLICATION_FEATURE_ENABLE_API",
    True,
)

APPLICATION_FEATURE_USE_REDIS = read_boolean_variable(
    "APPLICATION_FEATURE_USE_REDIS",
    False,
)

APPLICATION_FEATURE_ENABLE_REALTIME = read_boolean_variable(
    "APPLICATION_FEATURE_ENABLE_REALTIME",
    False,
)


# -------------------------------------------------------------------------
# Приложения
# -------------------------------------------------------------------------

INSTALLED_APPS = [
    # ---------------------------------------------------------------------
    # Встроенные приложения Django
    # ---------------------------------------------------------------------
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Расширения PostgreSQL: поля-диапазоны, массивы, полнотекстовый поиск.
    # Обязательно при использовании DateTimeRangeField и ArrayField.
    "django.contrib.postgres",

    # ---------------------------------------------------------------------
    # Сторонние приложения
    # ---------------------------------------------------------------------
    # Django REST Framework — основа REST API.
    "rest_framework",

    # Хранение токенов авторизации в базе данных.
    "rest_framework.authtoken",

    # Фильтрация наборов запросов по полям моделей (?recipient__icontains=...).
    "django_filters",

    # Автогенерация OpenAPI-схемы и интерактивной документации.
    "drf_spectacular",

    # ---------------------------------------------------------------------
    # Приложение, доступное в тестовом срезе проекта
    # ---------------------------------------------------------------------
    "messages.apps.MessagesConfig",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Корневой файл маршрутов.
ROOT_URLCONF = "configuration.urls"

# Шаблоны HTML-страниц.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            # Глобальная директория шаблонов проекта (/codebase/templates/).
            BASE_DIRECTORY / "templates",
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Точки входа для веб-серверов.
WSGI_APPLICATION = "configuration.wsgi.application"
ASGI_APPLICATION = "configuration.asgi.application"


# -------------------------------------------------------------------------
# База данных
# -------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": read_text("DATABASE_DEFAULT_NAME", "stormcast"),
        "USER": read_text("DATABASE_DEFAULT_USER", "admin"),
        "PASSWORD": read_text("DATABASE_DEFAULT_PASSWORD", ""),
        "HOST": read_text("DATABASE_INTERFACE_HOST", "database"),
        "PORT": read_integer_variable("DATABASE_INTERFACE_CONTAINER_PORT", 5432),
        "CONN_MAX_AGE": read_integer_variable("DATABASE_CONNECTION_MAX_AGE", 0),
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}


# -------------------------------------------------------------------------
# Модель пользователя
# -------------------------------------------------------------------------

# Используется встроенная модель django.contrib.auth.User.
#
# Если в проекте появятся требования, которых нет во встроенной модели
# (дополнительные поля, собственная логика авторизации), создайте
# приложение accounts с собственной моделью и раскомментируйте строку:
#
# AUTH_USER_MODEL = "accounts.User"
#
# Важно: менять AUTH_USER_MODEL после первых миграций нельзя без
# пересоздания базы данных. Если кастомная модель возможна в будущем —
# заведите её сразу.


# -------------------------------------------------------------------------
# Валидация паролей
# -------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 10,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# -------------------------------------------------------------------------
# Локализация и время
# -------------------------------------------------------------------------

LANGUAGE_CODE = "ru-RU"

TIME_ZONE = read_text("TIME_ZONE", "Europe/Moscow")

USE_I18N = True

USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# -------------------------------------------------------------------------
# Django REST Framework
# -------------------------------------------------------------------------

REST_FRAMEWORK = {
    # ---------------------------------------------------------------------
    # Документация
    # ---------------------------------------------------------------------
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",

    # ---------------------------------------------------------------------
    # Авторизация
    # ---------------------------------------------------------------------
    # SessionAuthentication — для HTML-интерфейса и браузерных запросов.
    # TokenAuthentication  — для служебных клиентов и интеграций.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],

    # ---------------------------------------------------------------------
    # Права доступа
    # ---------------------------------------------------------------------
    # По умолчанию API закрыт. Открытые эндпоинты помечаются явно
    # через AllowAny в конкретном представлении.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],

    # ---------------------------------------------------------------------
    # Фильтрация, сортировка, поиск
    # ---------------------------------------------------------------------
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],

    # ---------------------------------------------------------------------
    # Пагинация
    # ---------------------------------------------------------------------
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": read_integer_variable("API_PAGE_SIZE", 50),

    # ---------------------------------------------------------------------
    # Формат данных
    # ---------------------------------------------------------------------
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],

    # ---------------------------------------------------------------------
    # Прочее
    # ---------------------------------------------------------------------
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S%z",
    "NON_FIELD_ERRORS_KEY": "errors",
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

# Интерактивная документация доступна только при включённом признаке API
# и в режиме отладки. В продакшене её следует закрывать отдельно.
if APPLICATION_FEATURE_ENABLE_API:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
        "rest_framework.renderers.JSONRenderer",
    ]

if DEBUG:
    REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"].append(
        "rest_framework.renderers.BrowsableAPIRenderer"
    )


# -------------------------------------------------------------------------
# drf-spectacular (OpenAPI)
# -------------------------------------------------------------------------

SPECTACULAR_SETTINGS = {
    "TITLE": f"{APPLICATION_NAME} API",
    "DESCRIPTION": (
        "REST API приложения сообщений. Данные содержат реестр сообщений, "
        "рабочие буферы, неизменяемые ревизии и историю состояний."
    ),
    "VERSION": API_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": f"/api/{API_VERSION}",
    "ENUM_NAME_OVERRIDES": {
        "MessageTypeEnum": "messages.models.MessageType",
        "ReadinessStageEnum": "messages.models.ReadinessStage",
    },
    "SWAGGER_UI_SETTINGS": {
        "deepLinking": True,
        "persistAuthorization": True,
        "displayOperationId": False,
    },
}


# -------------------------------------------------------------------------
# Кэширование
# -------------------------------------------------------------------------

# Локальный кэш в памяти подходит для разработки и одиночного процесса.
# Для нескольких процессов или контейнеров требуется внешний кэш (Redis).

if APPLICATION_FEATURE_USE_REDIS:
    REDIS_DSN = read_text("EVENT_BUS_DSN", "redis://event-bus:6379/0")

    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_DSN,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "application_cache",
        }
    }


# -------------------------------------------------------------------------
# Фоновые задачи (Celery)
# -------------------------------------------------------------------------

# Отправка почты и сообщений АСПД выполняется в фоне, чтобы интерфейс
# не зависал на сетевых операциях. Celery подключается только при
# включённом признаке использования Redis.

if APPLICATION_FEATURE_USE_REDIS:
    CELERY_BROKER_URL = read_text("EVENT_BUS_DSN", "redis://event-bus:6379/0")
    CELERY_RESULT_BACKEND = CELERY_BROKER_URL
    CELERY_TASK_ALWAYS_EAGER = False
    CELERY_TASK_SERIALIZER = "json"
    CELERY_RESULT_SERIALIZER = "json"
    CELERY_ACCEPT_CONTENT = ["json"]
    CELERY_TIMEZONE = TIME_ZONE
    CELERY_TASK_TRACK_STARTED = True
    CELERY_TASK_TIME_LIMIT = 300
    CELERY_TASK_SOFT_TIME_LIMIT = 240
else:
    # Задачи выполняются синхронно в текущем процессе.
    # Приемлемо для разработки, неприемлемо для продакшена.
    CELERY_TASK_ALWAYS_EAGER = True


# -------------------------------------------------------------------------
# Почтовые настройки
# -------------------------------------------------------------------------

EMAIL_BACKEND = read_text(
    "MAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)

EMAIL_HOST = read_text("MAIL_SERVER_HOST", "mail-server")
EMAIL_PORT = read_integer_variable("MAIL_SERVER_INTERFACE_CONTAINER_PORT", 1025)
EMAIL_USE_TLS = read_boolean_variable("MAIL_SERVER_USE_TLS", False)
EMAIL_USE_SSL = read_boolean_variable("MAIL_SERVER_USE_SSL", False)
EMAIL_HOST_USER = read_text("MAIL_SERVER_USER")
EMAIL_HOST_PASSWORD = read_text("MAIL_SERVER_PASSWORD")

DEFAULT_FROM_EMAIL = read_text("MAIL_SERVER_DEFAULT_EMAIL", "stormcast@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = f"[{APPLICATION_NAME}] "

# Количество повторных попыток при сбоях SMTP.
EMAIL_SEND_MAX_RETRIES = read_integer_variable("MAIL_SEND_MAX_RETRIES", 3)


# -------------------------------------------------------------------------
# Объектное хранилище (MinIO / S3)
# -------------------------------------------------------------------------

OBJECT_STORAGE_ADDRESS = read_text("OBJECT_STORAGE_ADDRESS", "minio:9000")
OBJECT_STORAGE_BUCKET = read_text("OBJECT_STORAGE_BUCKET", "stormcast")
OBJECT_STORAGE_DEFAULT_USER = read_text("OBJECT_STORAGE_DEFAULT_USER", "admin")
OBJECT_STORAGE_DEFAULT_PASSWORD = read_text("OBJECT_STORAGE_DEFAULT_PASSWORD", "password")
OBJECT_STORAGE_USE_SSL = read_boolean_variable("OBJECT_STORAGE_USE_SSL", False)

# Подключение django-storages выполняется после установки пакета.
# Раскомментируйте блок и добавьте "storages" в INSTALLED_APPS.
#
# STORAGES = {
#     "default": {
#         "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
#     },
#     "staticfiles": {
#         "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
#     },
# }
# AWS_S3_ENDPOINT_URL = f"http{'s' if OBJECT_STORAGE_USE_SSL else ''}://{OBJECT_STORAGE_ADDRESS}"
# AWS_STORAGE_BUCKET_NAME = OBJECT_STORAGE_BUCKET
# AWS_S3_ACCESS_KEY_ID = OBJECT_STORAGE_DEFAULT_USER
# AWS_S3_SECRET_ACCESS_KEY = OBJECT_STORAGE_DEFAULT_PASSWORD
# AWS_S3_SIGNATURE_VERSION = "s3v4"
# AWS_QUERYSTRING_AUTH = False


# -------------------------------------------------------------------------
# Статические и медиафайлы
# -------------------------------------------------------------------------

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIRECTORY / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIRECTORY / "media"


# -------------------------------------------------------------------------
# Безопасность
# -------------------------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if DEBUG:
    # Режим разработки: HTTP, подробные страницы ошибок.
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False
else:
    # Продакшен: HTTPS обязателен.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = read_boolean_variable("APPLICATION_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = read_integer_variable("APPLICATION_HSTS_SECONDS", 31_536_000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# -------------------------------------------------------------------------
# Протоколирование
# -------------------------------------------------------------------------

LOG_LEVEL = read_text("APPLICATION_LOG_LEVEL", "DEBUG" if DEBUG else "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
        "detailed": {
            "format": (
                "{asctime} {levelname} {name} "
                "[{module}.{funcName}:{lineno}] {message}"
            ),
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "detailed" if DEBUG else "standard",
        },
    },

    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },

    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },

        # Приложения проекта.
        "dispatch": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "bulletin": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "distribution": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "delivery": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
    },
}
