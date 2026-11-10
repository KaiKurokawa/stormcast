"""Маршруты API документов."""

from rest_framework.routers import DefaultRouter

from documents.views import (
    DocumentEntityViewSet,
    RevisionBufferViewSet,
    RevisionViewSet,
    StateViewSet,
)


router = DefaultRouter()
router.register("documents", DocumentEntityViewSet, basename="document")
router.register("document-buffers", RevisionBufferViewSet, basename="document-buffer")
router.register("document-revisions", RevisionViewSet, basename="document-revision")
router.register("document-states", StateViewSet, basename="document-state")

from documents.views import TemplateEntityViewSet, TemplateRevisionViewSet

router.register("document-templates", TemplateEntityViewSet, basename="document-template")
router.register("document-template-revisions", TemplateRevisionViewSet, basename="document-template-revision")
