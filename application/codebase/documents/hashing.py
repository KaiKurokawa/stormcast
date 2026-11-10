"""Канонические BLAKE3-хеши полезной нагрузки документов."""

from blake3 import blake3
import rfc8785


def document_revision_content_hash(*, template_id, out_number, topic, field_overrides, message_bindings, note, details):
    """Хеширует снимок документа без автора, родителя и временных меток."""
    return blake3(rfc8785.dumps({
        "template_id": str(template_id), "out_number": out_number,
        "topic": topic, "field_overrides": field_overrides,
        "message_bindings": message_bindings, "note": note, "details": details,
    })).digest()


def template_revision_content_hash(*, code, title, description, body_html, field_schema, default_overrides):
    """Хеширует содержимое версии шаблона."""
    return blake3(rfc8785.dumps({
        "code": code, "title": title, "description": description,
        "body_html": body_html, "field_schema": field_schema,
        "default_overrides": default_overrides,
    })).digest()


def state_content_hash(*, readiness_stage, is_archived, is_deleted, details):
    """Хеширует состояние без контекста записи журнала."""
    return blake3(rfc8785.dumps({
        "readiness_stage": readiness_stage, "is_archived": bool(is_archived),
        "is_deleted": bool(is_deleted), "details": {} if details is None else details,
    })).digest()
