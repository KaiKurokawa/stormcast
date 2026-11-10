"""
Структурированное контекстное логирование с использованием ContextVars.

Этот модуль предоставляет гибкий и структурированный механизм контекста логирования, 
основанный на `contextvars` из Python. Он поддерживает как постоянный, так и временный 
контекст логирования для локальных (на уровне функций) и связанных (на уровне приложения) областей.

Система обеспечивает последовательное обогащение записей логов диагностическими и 
бизнес-метаданными (например, request_id, user_id, маркеры этапов), сохраняя при этом 
вызовы логирования чистыми и декларативными. Также включена специальная обработка 
исключений и трассировок стека, замер времени этапов с помощью `log_stage` и декоратор 
`with_log_context` для автоматического внедрения контекста из аргументов функции.

Особенности:
    - Изолированное распространение контекста между асинхронными задачами и потоками
    - Автоматическое форматирование исключений и захват трассировки стека
    - Ограниченное по времени логирование этапов с измерением продолжительности
    - Декораторы для интеграции структурированного логирования
    - Опциональная интеграция с JSON-форматтером и фильтром логирования

Типичные сценарии использования:
    - Распределенная трассировка (например, передача идентификаторов запроса/сессии/задачи)
    - Наблюдаемость и диагностика в асинхронных приложениях
    - Чистое логирование этапов и продолжительности в ETL-конвейерах / конвейерах обработки

Использование:
    >>> from context_logging import with_log_context, log_stage
    >>> @with_log_context(user_id="uid")
    ... def process(uid): ...

    >>> with log_stage("data_import"):
    ...     run_import()
"""

import inspect
import json
import logging
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Callable, ContextManager, Literal

__all__ = [
    "add_bound_context",
    "add_local_context",
    "log_stage",
    "replace_bound_context",
    "replace_local_context",
    "with_log_context"
]


# --- Хранилище переменных контекста ---

# Связанный контекст хранит долгоживущие, сквозные идентификаторы (например, session_id).
_bound_context: ContextVar[dict[str, Any]] = ContextVar("_bound_context", default={})
# Локальный контекст хранит временные данные, специфичные для функции или этапа.
_local_context: ContextVar[dict[str, Any]] = ContextVar("_local_context", default={})


# --- Обработчики специальных полей ---

def _handle_exception(fields: dict[str, Any]) -> None:
    """Форматирует объект исключения в структурированные поля."""
    if "exception" in fields and isinstance(fields["exception"], BaseException):
        exception_object = fields.pop("exception")
        fields["exception_class"] = exception_object.__class__.__name__
        fields["exception_message"] = str(exception_object)
        fields["stack_trace"] = traceback.format_exc()

def _handle_stack_trace(fields: dict[str, Any]) -> None:
    """Добавляет трассировку стека в контекст, если это запрошено."""
    if fields.get("stack_trace") is True:
        # Срез [:-2] удаляет кадр этого обработчика и его вызывающего объекта.
        fields["stack_trace"] = "".join(traceback.format_stack()[:-2])

# Реестр обработчиков. Легко расширяем для будущих специальных ключевых слов.
SPECIAL_HANDLERS: dict[str, Callable[[dict[str, Any]], None]] = {
    "exception": _handle_exception,
    "stack_trace": _handle_stack_trace,
}

def _process_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Обрабатывает словарь полей, применяя все специальные обработчики."""
    processed_fields = fields.copy()
    for name, handler in SPECIAL_HANDLERS.items():
        if name in processed_fields:
            handler(processed_fields)
    return processed_fields


# --- Утилиты контекста ---

def get_log_context() -> dict[str, Any]:
    """
    Возвращает текущий структурированный контекст лога.

    Объединяет связанный и локальный контексты, при этом значения локального 
    контекста перезаписывают значения связанного контекста в случае коллизии ключей.

    Возвращает:
        Полный текущий контекст.
    """

    bound_context = _bound_context.get()
    local_context = _local_context.get()
    return {**bound_context, **local_context}


# --- Основные функции локального контекста ---

def add_local_context_permanent(**fields: Any) -> None:
    """Добавляет поля в текущий локальный контекст лога на постоянной основе."""
    current_context = _local_context.get().copy()
    processed_fields = _process_fields(fields)
    current_context.update(processed_fields)
    _local_context.set(current_context)


def replace_local_context_permanent(**fields: Any) -> None:
    """Заменяет текущий локальный контекст лога на постоянной основе."""
    processed_fields = _process_fields(fields)
    _local_context.set(processed_fields)


@contextmanager
def add_local_context_temporary(**fields: Any) -> ContextManager[dict[str, Any]]:
    """Временно добавляет поля в локальный контекст лога."""
    processed_fields = _process_fields(fields)
    token = _local_context.set({**_local_context.get(), **processed_fields})
    try:
        yield processed_fields
    finally:
        _local_context.reset(token)


@contextmanager
def replace_local_context_temporary(**fields: Any) -> ContextManager[dict[str, Any]]:
    """Временно заменяет локальный контекст лога."""
    processed_fields = _process_fields(fields)
    token = _local_context.set(processed_fields)
    try:
        yield processed_fields
    finally:
        _local_context.reset(token)


# --- Основные функции связанного контекста ---

def add_bound_context_permanent(**fields: Any) -> None:
    """Добавляет поля в текущий связанный контекст лога на постоянной основе."""
    current_context = _bound_context.get().copy()
    processed_fields = _process_fields(fields)
    current_context.update(processed_fields)
    _bound_context.set(current_context)


def replace_bound_context_permanent(**fields: Any) -> None:
    """Заменяет текущий связанный контекст лога на постоянной основе."""
    processed_fields = _process_fields(fields)
    _bound_context.set(processed_fields)


@contextmanager
def add_bound_context_temporary(**fields: Any) -> ContextManager[dict[str, Any]]:
    """Временно добавляет поля в связанный контекст лога."""
    processed_fields = _process_fields(fields)
    token = _bound_context.set({**_bound_context.get(), **processed_fields})
    try:
        yield processed_fields
    finally:
        _bound_context.reset(token)


@contextmanager
def replace_bound_context_temporary(**fields: Any) -> ContextManager[dict[str, Any]]:
    """Временно заменяет связанный контекст лога."""
    processed_fields = _process_fields(fields)
    token = _bound_context.set(processed_fields)
    try:
        yield processed_fields
    finally:
        _bound_context.reset(token)


# --- Публичный API ---

add_local_context = add_local_context_temporary
replace_local_context = replace_local_context_temporary
add_bound_context = add_bound_context_temporary
replace_bound_context = replace_bound_context_temporary


@contextmanager
def log_stage(stage_name: str, **extra_fields: Any) -> ContextManager[dict[str, Any]]:
    """
    Контекстный менеджер для автоматического логирования начала, завершения 
    и продолжительности блока кода (этапа).

    Аргументы:
        stage_name:
            Имя этапа.
        **extra_fields:
            Дополнительные пары ключ-значение для добавления в локальный контекст 
            на время выполнения этого этапа.

    Возвращает (yields):
        Словарь, в который можно добавлять итоговые данные.
        Эти данные будут включены в итоговое сообщение лога.

    Примеры:
        >>> with log_stage("data_processing") as stage_data:
        ...     # Какая-то работа...
        ...     stage_data["items_processed"] = 100
    """

    logger = logging.getLogger()
    start_time = time.monotonic()
    summary_data = {}
    stage_context = {"stage": stage_name, **extra_fields}

    with add_local_context(**stage_context):
        logger.info("Stage starting.")
        try:
            yield summary_data
        except Exception:
            duration = time.monotonic() - start_time
            summary_data["duration_seconds"] = round(duration, 4)
            with add_local_context(**summary_data):
                 logger.error("Stage failed.")
            raise
        else:
            duration = time.monotonic() - start_time
            summary_data["duration_seconds"] = round(duration, 4)
            with add_local_context(**summary_data):
                logger.info("Stage completed.")


def with_log_context(*argument_names: str, **resolve_map: str) -> Callable:
    """
    Декоратор для создания свежего локального контекста для функции, 
    заполненного её аргументами.

    Связанный контекст сохраняется.

    Аргументы:
        *argument_names:
            Имена аргументов для логирования с тем же ключом.
        **resolve_map:
            Сопоставляет новый ключ контекста с именем аргумента функции.
            Пример: `request_id="req_id"` логирует значение 
            аргумента `req_id` под ключом `request_id`.
    """

    def decorator(function: Callable) -> Callable:
        """
        Внутренний декоратор, создающий обертку для синхронной или асинхронной функции.
        """
        signature = inspect.signature(function)
        argument_map = {name: name for name in argument_names}
        argument_map.update({resolved_name: name for resolved_name, name in resolve_map.items()})

        if inspect.iscoroutinefunction(function):
            async def async_wrapper(*arguments, **keywords):
                """Асинхронная обертка, внедряющая контекст перед выполнением."""
                bound_arguments = signature.bind(*arguments, **keywords)
                bound_arguments.apply_defaults()
                fields = {
                    resolved_name: bound_arguments.arguments.get(name)
                    for resolved_name, name in argument_map.items()
                }
                with replace_local_context(**fields):
                    return await function(*arguments, **keywords)
            return async_wrapper

        else:
            def sync_wrapper(*arguments, **keywords):
                """Синхронная обертка, внедряющая контекст перед выполнением."""
                bound_arguments = signature.bind(*arguments, **keywords)
                bound_arguments.apply_defaults()
                fields = {
                    resolved_name: bound_arguments.arguments.get(name)
                    for resolved_name, name in argument_map.items()
                }
                with replace_local_context(**fields):
                    return function(*arguments, **keywords)
            return sync_wrapper

    return decorator


# --- Утилиты интеграции логирования ---

class ContextFilter(logging.Filter):
    """Фильтр логирования, внедряющий текущий контекст лога в каждую запись LogRecord."""
    def __init__(self, name: str = "", context_key: str = "log_context"):
        """Инициализирует фильтр с заданным именем и ключом контекста."""
        super().__init__(name)
        self.context_key = context_key

    def filter(self, record: logging.LogRecord) -> bool:
        """Прикрепляет контекст из get_log_context() к LogRecord."""
        setattr(record, self.context_key, get_log_context())
        return True


class ContextJSONFormatter(logging.Formatter):
    """Форматтер логирования, выводящий записи лога в виде JSON-строк, 
    автоматически включая структурированный контекст лога."""
    def __init__(
        self,
        message_format: str | None = None,
        date_format: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        context_key: str = "log_context"
    ):
        """Инициализирует JSON-форматтер с параметрами форматирования и ключом контекста."""
        super().__init__(message_format, date_format, style)
        self.context_key = context_key

    def format(self, record: logging.LogRecord) -> str:
        """Форматирует LogRecord в строку JSON."""
        log_data = {
            "date": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line_number": record.lineno,
            "file": record.pathname,
        }

        # Объединяет структурированный контекст, если он существует в записи.
        if hasattr(record, self.context_key):
            context = getattr(record, self.context_key)
            if isinstance(context, dict):
                log_data.update(context)

        # Добавляет информацию об исключении, если она присутствует.
        if record.exc_info:
            log_data["exception_details"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)
