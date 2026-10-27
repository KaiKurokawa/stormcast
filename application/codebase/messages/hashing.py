from blake3 import blake3
import rfc8785


def _range_payload(period):
    if period is None:
        return None
    if getattr(period, "isempty", False):
        return {"empty": True}

    return {
        "lower": period.lower.isoformat() if period.lower is not None else None,
        "upper": period.upper.isoformat() if period.upper is not None else None,
        "bounds": period.bounds,
    }


def revision_content_hash(*, message_type, period, region, text, note, details):
    payload = {
        "type": message_type,
        "period": _range_payload(period),
        "region": region,
        "text": text,
        "note": note,
        "details": {} if details is None else details,
    }
    return blake3(rfc8785.dumps(payload)).digest()


def state_content_hash(
    *, readiness_stage, is_starred, is_archived, is_deleted, details
):
    payload = {
        "readiness_stage": readiness_stage,
        "is_starred": bool(is_starred),
        "is_archived": bool(is_archived),
        "is_deleted": bool(is_deleted),
        "details": {} if details is None else details,
    }
    return blake3(rfc8785.dumps(payload)).digest()
