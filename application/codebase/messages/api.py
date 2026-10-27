from rest_framework.routers import DefaultRouter

from messages.views import (
    MessageEntityViewSet,
    RevisionBufferViewSet,
    RevisionViewSet,
    StateViewSet,
)


router = DefaultRouter()
router.register("messages", MessageEntityViewSet, basename="message")
router.register("buffers", RevisionBufferViewSet, basename="message-buffer")
router.register("revisions", RevisionViewSet, basename="message-revision")
router.register("states", StateViewSet, basename="message-state")
