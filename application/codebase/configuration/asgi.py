"""
---------------------------------------------------------------------------
Асинхронный веб-шлюз
---------------------------------------------------------------------------

Стандарт ASGI применяется асинхронными серверами приложений, например uvicorn.

При включённом признаке APPLICATION_FEATURE_ENABLE_REALTIME сюда
добавляется маршрутизация Django Channels (WebSocket).
"""

import os

from django.core.asgi import get_asgi_application


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "configuration.settings",
)

application = get_asgi_application()
