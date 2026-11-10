"""
Конфигурация структурированного логирования с использованием structlog и стандартной библиотеки.

Этот модуль предоставляет гибкую и учитывающую окружение настройку логирования, 
построенную поверх стандартного логирования Python и structlog. Он поддерживает 
логирование в консоль и файл с опциональной ротацией, внедрение структурированного 
контекста и совместимость с асинхронным режимом.

Спроектирован для модульной интеграции в приложения с минимальными затратами на настройку.

Использование:
    >>> from logging_setup import setup_logging
    >>> setup_logging(environment="development")
    >>> log = structlog.get_logger(__name__)
    >>> log.info("Логирование готово", example=True)
"""

import logging
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Callable, Literal

import structlog
from structlog.types import EventDict, Processor

__all__ = ["setup_logging"]


def _create_location_processor(
    logger: logging.Logger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Возвращает новый словарь событий, обогащенный данными об источнике вызова.

    Добавляет имя функции, имя модуля, номер строки и имя файла 
    исходного места вызова лога в структурированный словарь событий лога.

    Аргументы:
        logger:
            Экземпляр логгера стандартной библиотеки.
        method_name:
            Имя метода логирования (например, "info", "error").
        event_dict:
            Словарь событий для обогащения.

    Возвращает:
        Обогащенный словарь событий, включающий информацию об источнике вызова.
    """

    frame = logging.currentframe()
    if frame is not None:
        caller = frame.f_back.f_back  # Возврат к исходному вызову лога.
        if caller is not None:
            enriched = event_dict.copy()
            enriched["function"] = caller.f_code.co_name
            enriched["module"] = caller.f_globals.get("__name__")
            enriched["line"] = caller.f_lineno
            enriched["file"] = caller.f_code.co_filename
            return enriched
    return event_dict


def _create_context_processor(
    custom_context_getter: Callable[[], dict[str, object]]
) -> Processor:
    """
    Создает процессор structlog, добавляющий пользовательский контекст в логи.

    Аргументы:
        custom_context_getter:
            Вызываемый объект, возвращающий словарь дополнительного контекста лога.

    Возвращает:
        Функцию-процессор structlog, обновляющую словарь событий.
    """

    def processor(
        logger: logging.Logger, method_name: str, event_dict: EventDict
    ) -> EventDict:
        """
        Обрабатывает событие, добавляя пользовательский контекст.

        Аргументы:
            logger: Экземпляр логгера.
            method_name: Имя метода логирования.
            event_dict: Словарь событий для обновления.

        Возвращает:
            Обновленный словарь событий или словарь с информацией об ошибке.
        """
        try:
            return {**event_dict, **custom_context_getter()}
        except Exception as exc:
            return {**event_dict, "custom_context_error": str(exc)}

    return processor


def _create_base_processors() -> list[Processor]:
    """
    Возвращает базовый список процессоров structlog без пользовательских 
    или процессоров определения местоположения.

    Возвращает:
        Список стандартных функций-процессоров structlog.
    """

    # Процессоры — это функции, которые обогащают и форматируют запись лога.
    # Их порядок имеет значение.
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.dict_tracebacks,
        structlog.processors.format_exc_info,
        structlog.processors.StackInfoRenderer(),
    ]


def _create_formatter(
    processors: list[Processor], environment: Literal["development", "production"]
) -> logging.Formatter:
    """
    Создает ProcessorFormatter с рендерингом, зависящим от окружения.

    Аргументы:
        processors:
            Список процессоров structlog, запускаемых перед рендерингом.
        environment:
            'development' для цветных логов в консоли, 'production' для JSON.

    Возвращает:
        Настроенный экземпляр structlog ProcessorFormatter.
    """

    if environment == "development":
        # Для разработки используется цветной консольный рендерер, если это TTY.
        use_colors = sys.stdout.isatty()
        renderer = structlog.dev.ConsoleRenderer(colors=use_colors)
    else:
        # Для продакшена используется чистый JSON-рендерер.
        renderer = structlog.processors.JSONRenderer(sort_keys=True)

    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=processors,
        processor=renderer,
    )


def _create_console_handler(
    formatter: logging.Formatter, level: int
) -> logging.Handler:
    """
    Создает и настраивает обработчик логирования в консоль.

    Аргументы:
        formatter:
            Экземпляр форматтера для форматирования записей лога.
        level:
            Минимальный уровень логирования для этого обработчика.

    Возвращает:
        Настроенный StreamHandler для stdout.
    """

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _create_file_handler(
    log_path: Path | str | None,
    formatter: logging.Formatter,
    file_level: int,
    rotation_type: Literal["size", "time", None],
    rotation_when: str,
    file_size_limit: int,
    backup_count: int,
) -> logging.Handler | None:
    """
    Создает обработчик логирования в файл с опциональной ротацией.

    Аргументы:
        log_path:
            Путь к файлу лога.
        formatter:
            Экземпляр форматтера для форматирования записей лога.
        file_level:
            Минимальный уровень логирования для этого обработчика.
        rotation_type:
            Стратегия ротации ('size', 'time' или None).
        rotation_when:
            Интервал для ротации по времени (например, 'midnight', 'h').
        file_size_limit:
            Максимальный размер файла в мебибайтах для ротации по размеру.
        backup_count:
            Количество сохраняемых ротированных файлов логов.

    Возвращает:
        Настроенный обработчик файлового логирования или None в случае ошибки создания.
    """

    if not log_path:
        return None

    try:
        resolved_path = Path(log_path).resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)

        match rotation_type:
            case "size":
                handler = RotatingFileHandler(
                    resolved_path,
                    maxBytes=file_size_limit * (1024 * 1024),
                    backupCount=backup_count,
                    encoding="utf-8",
                )
            case "time":
                handler = TimedRotatingFileHandler(
                    resolved_path,
                    when=rotation_when,
                    backupCount=backup_count,
                    encoding="utf-8",
                )
            case None | _:
                handler = logging.FileHandler(resolved_path, encoding="utf-8")

        handler.setLevel(file_level)
        handler.setFormatter(formatter)
        return handler

    except (PermissionError, OSError) as exception:
        # Если файловый логгер не работает, выводится предупреждение в консоль, и выполнение продолжается.
        print(
            f"Warning: Could not create log file at: '{log_path}'\n"
            f"Error: {exception}", file=sys.stderr
        )


def _normalize_log_level(level: int | str) -> int:
    """
    Нормализует входной уровень логирования до целочисленного значения.

    Аргументы:
        level:
            Уровень логирования в виде целого числа или строки (без учета регистра).

    Возвращает:
        Уровень логирования в виде целого числа.

    Исключения:
        ValueError: Если уровень некорректен.
    """

    match level:
        case str():
            numeric_level = logging.getLevelName(level.upper())
            if not isinstance(numeric_level, int):
                raise ValueError(f"Invalid log level string: {level}")
            return numeric_level
        case int():
            return level
        case _:
            raise ValueError(f"Invalid log level type: {level}")


def setup_logging(
    environment: Literal["development", "production"] = "development",
    log_path: Path | str | None = None,
    async_mode: bool = True,
    custom_context_getter: Callable[[], dict[str, object]] | None = None,

    console_level: int | str = "info",
    file_level: int | str = "debug",

    rotation_type: Literal["size", "time", None] = "size",
    rotation_when: str = "midnight",
    file_size_limit: int = 5,
    backup_count: int = 3,
) -> None:
    """
    Настраивает общеприложенческое логирование с использованием structlog.

    Эта функция устанавливает конвейер логирования, адаптирующийся к среде выполнения. 
    В режиме 'development' логи читаемы человеком и цветные. В режиме 'production' 
    они структурированы в формате JSON для машинного парсинга.

    Поддерживает как автономное использование, так и интеграцию со системами 
    структурированного контекста, такими как `log_context`.

    Примечания:
        Если `async_mode` равен True, этот логгер предназначен для использования 
        в приложении, работающем с циклом событий (например, asyncio). Корректное 
        завершение работы должно обрабатываться фреймворком приложения.

    Аргументы:
        environment:
            Рабочее окружение: 'development' (консоль) или 'production' (JSON).
        log_path:
            Опциональный путь для записи файловых логов.
        async_mode:
            Использовать ли асинхронную обработку логов.
        custom_context_getter:
            Опциональный вызываемый объект для внедрения структурированного контекста.
        console_level:
            Минимальный уровень логирования для вывода в консоль.
        file_level:
            Минимальный уровень логирования для вывода в файл.
        rotation_type:
            Стратегия ротации ('size', 'time' или None).
        rotation_when:
            Интервал для ротации по времени (например, 'midnight', 'h').
        file_size_limit:
            Максимальный размер файла в мебибайтах для ротации по размеру.
        backup_count:
            Количество сохраняемых ротированных файлов логов.

    Примеры:
        - Базовая настройка для локальной разработки:
            >>> setup_logging(environment="development")
            >>> log = structlog.get_logger("my_app")
            >>> # Вывод будет цветной, читаемой человеком строкой в консоли.
            >>> log.info("Пользователь вошел в систему", user_id=123)

        - Продакшен-настройка с файловым логированием и разными уровнями:
            >>> setup_logging(
            ...     environment="production",
            ...     custom_context_getter=get_log_context,
            ...     console_level="info",
            ...     file_level="debug",
            ...     log_path="/var/log/my_app.log",
            ...     rotation_type="size"
            ... )
            >>> log = structlog.get_logger("my_service")
            >>> # Это сообщение будет записано только в файл лога.
            >>> log.debug("Подключение к базе данных", db_host="prod-db")

        - Асинхронная настройка в приложении на asyncio:
            >>> import asyncio
            >>> async def main():
            ...     # Конфигурация должна вызываться внутри запущенного цикла событий,
            ...     # чтобы async_mode=True работал корректно.
            ...     setup_logging(environment="production", async_mode=True)
            ...     log = structlog.get_logger()
            ...     await log.info("Асинхронная задача выполнена.")
    """

    console_level = _normalize_log_level(console_level)
    file_level = _normalize_log_level(file_level)

    # Настройка корневого логгера.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Устанавливается минимальный уровень, чтобы не блокировать сообщения до их попадания в обработчик.
    root_logger.setLevel(min(console_level, file_level))

    processors = _create_base_processors()
    processors.append(_create_location_processor)

    if custom_context_getter:
        custom_processor = _create_context_processor(custom_context_getter)
        processors.insert(0, custom_processor)

    formatter = _create_formatter(processors, environment)
    handlers = [_create_console_handler(formatter, console_level)]

    if log_path:
        file_handler = _create_file_handler(
            log_path=log_path,
            formatter=formatter,
            file_level=file_level,
            rotation_type=rotation_type,
            rotation_when=rotation_when,
            file_size_limit=file_size_limit,
            backup_count=backup_count,
        )
        handlers.append(file_handler)

    for handler in handlers:
        root_logger.addHandler(handler)

    structlog.configure(
        processors=processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=(
            structlog.stdlib.AsyncBoundLogger
                if async_mode
                else structlog.stdlib.BoundLogger
        ),
        cache_logger_on_first_use=True,
    )
