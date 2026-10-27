"""
---------------------------------------------------------------------------
Главные URL-маршруты
---------------------------------------------------------------------------
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    # ---------------------------------------------------------------------
    # Административный интерфейс
    # ---------------------------------------------------------------------
    path("admin/", admin.site.urls),

    # ---------------------------------------------------------------------
    # REST API
    # ---------------------------------------------------------------------
    # Префикс /api/v1/ объявляется здесь, а содержимое — в configuration/api.py.
    path(
        f"api/{settings.API_VERSION}/",
        include(("configuration.api", "api"), namespace="api"),
    ),
]


# -------------------------------------------------------------------------
# Раздача статических и медиафайлов в режиме разработки
# -------------------------------------------------------------------------

if settings.DEBUG:
    urlpatterns.extend(
        static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    )
    urlpatterns.extend(
        static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    )


# -------------------------------------------------------------------------
# Настройки административного интерфейса
# -------------------------------------------------------------------------

admin.site.site_header = settings.APPLICATION_NAME
admin.site.site_title = settings.APPLICATION_NAME
admin.site.index_title = settings.APPLICATION_TITLE
