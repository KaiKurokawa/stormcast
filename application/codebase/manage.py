#!/usr/bin/env python
"""Файл запуска команд управления проектом."""

from os import environ as environment_variables
from sys import exit as exit_process


def main() -> None:
    """Запускает выполнение команды управления проектом."""

    environment_variables.setdefault(
        "DJANGO_SETTINGS_MODULE",
        "configuration.settings",
    )

    try:
        from django.core.management import execute_from_command_line

    except ImportError as import_error:
        raise ImportError(
            "Джанго не найден. Убедись, что виртуальное окружение активировано "
            "и зависимости установлены."
        ) from import_error

    execute_from_command_line()


if __name__ == "__main__":
    try:
        main()

    except RuntimeError as configuration_error:
        print(f"Ошибка конфигурации: {configuration_error}")
        exit_process(1)
