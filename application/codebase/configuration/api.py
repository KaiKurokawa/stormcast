"""
---------------------------------------------------------------------------
Модуль: Корневой маршрутизатор REST API
---------------------------------------------------------------------------

Назначение:
    Собирает маршруты всех приложений проекта в единое пространство
    имён и добавляет точки входа документации OpenAPI.

Соглашение:
    Каждое приложение, предоставляющее эндпоинты, содержит файл api.py
    с объектом `router` типа rest_framework.routers.DefaultRouter.

    Пример dispatch/api.py:

        from rest_framework import routers

        from dispatch.views import DispatchViewSet

        router = routers.DefaultRouter()
        router.register("dispatches", DispatchViewSet, basename="dispatch")
"""

from importlib import import_module
from logging import getLogger

from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from configuration.settings import DEBUG


logger = getLogger(__name__)


# -------------------------------------------------------------------------
# Перечень приложений, предоставляющих эндпоинты API
# -------------------------------------------------------------------------

API_APPLICATIONS = (
    "messages",
)


api_router = DefaultRouter()


for application_name in API_APPLICATIONS:
    module_path = f"{application_name}.api"

    try:
        application_api_module = import_module(module_path)

    except ModuleNotFoundError as import_error:
        # Приложение ещё не реализовало файл api.py — это ожидаемая
        # ситуация на ранней стадии разработки. Обрабатываем только
        # случай, когда не найден именно этот конкретный модуль,
        # а не какая-то из его зависимостей.
        if import_error.name == module_path:
            logger.info(
                "Приложение «%s» пока не предоставляет эндпоинты "
                "(файл %s не найден).",
                application_name,
                module_path,
            )
            continue

        # Другой модуль не найден — это настоящая ошибка импорта,
        # пробрасываем её дальше.
        raise

    except ImportError as import_error:
        # Любая другая ошибка импорта (синтаксис, отсутствие зависимостей)
        # не должна оставаться незамеченной.
        logger.exception(
            "Не удалось загрузить маршруты приложения «%s»: %s",
            application_name,
            import_error,
        )
        raise

    api_router.registry.extend(application_api_module.router.registry)

    logger.info(
        "Подключены маршруты приложения «%s»: %s.",
        application_name,
        ", ".join(
            prefix for prefix, _viewset, _basename in application_api_module.router.registry
        ) or "нет зарегистрированных эндпоинтов",
    )


# -------------------------------------------------------------------------
# Маршруты
# -------------------------------------------------------------------------

@api_view(("GET",))
@permission_classes((AllowAny,))
def health(request):
    return Response({"status": "ok"})


urlpatterns = [path("health/", health, name="health")]

if DEBUG:
    # Документация доступна только в режиме разработки.
    # Для продакшена требуется отдельная защита (VPN, базовая авторизация).
    urlpatterns.extend(
        [
            path(
                "schema/",
                SpectacularAPIView.as_view(),
                name="schema",
            ),
            path(
                "docs/",
                SpectacularSwaggerView.as_view(url_name="schema"),
                name="swagger-ui",
            ),
            path(
                "redoc/",
                SpectacularRedocView.as_view(url_name="schema"),
                name="redoc",
            ),
        ]
    )

urlpatterns.extend(api_router.urls)
