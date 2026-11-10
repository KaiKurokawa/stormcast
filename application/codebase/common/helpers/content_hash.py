from typing import Any
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

import blake3
import rfc8785


def _normalize_value(value: Any) -> Any:
    """
    Рекурсивно приводит значение к JSON-совместимому виду.

    Это необходимо, потому что rfc8785 работает только
    со стандартными типами: dict, list, str, int, float, bool, None.

    Обработанные типы:
        - datetime/date/time → ISO 8601 строка
        - Decimal → строка
        - UUID → строка
        - bytes → hex-строка
        - dict → рекурсивная нормализация значений
        - list/tuple → рекурсивная нормализация элементов
    """

    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, bytes):
        return value.hex()

    # str, int, float, bool, None — уже JSON-совместимы
    return value


def compute_content_hash(*values: Any) -> bytes:
    """
    Универсальная функция вычисления контентного хеша.

    Принимает любое количество аргументов любого типа.
    Каждый аргумент приводится к каноническому виду и
    хешируется алгоритмом BLAKE3 с сохранением исходного порядка передачи.

    Аргументы:
        *values: произвольные значения (строки, числа, словари, списки,
                 байты, datetime, Decimal, UUID, None)

    Возвращает:
        bytes: 32 байта (256 бит) хеша BLAKE3

    Алгоритм:
        1. Каждый аргумент нормализуется к JSON-совместимому виду
        2. Каждый аргумент сериализуется в канонический JSON (RFC 8785)
        3. Аргументы соединяются нулевым байтом (защита от коллизий)
        4. Вычисляется BLAKE3 хеш
    """

    canonical_parts: list[bytes] = []

    for val in values:
        # 1. Нормализация к JSON-совместимому виду
        normalized = _normalize_value(val)

        # 2. Каноническая сериализация по RFC 8785 (возвращает байты)
        canonical_bytes = rfc8785.dumps(normalized)

        canonical_parts.append(canonical_bytes)

    # 3. Конкатенация с разделителем \x00 (защита от коллизий)
    combined = b"\x00".join(canonical_parts)

    # 4. BLAKE3 хеш
    return blake3.blake3(combined).digest()
