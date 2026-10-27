"""
---------------------------------------------------------------------------
Чтение переменных окружения
---------------------------------------------------------------------------

Назначение:
    Вспомогательные функции для безопасного чтения и преобразования
    переменных окружения. Вынесены из settings.py, чтобы файл настроек
    содержал только настройки.
"""

from os import environ as environment_variables


def read_text(variable_name: str, default_value: str = "") -> str:
    """
    Возвращает значение переменной окружения либо значение по умолчанию.
    """

    return environment_variables.get(variable_name, default_value)


def read_required_text(variable_name: str) -> str:
    """
    Возвращает значение переменной окружения.

    Прерывает запуск приложения, если переменная не заполнена.
    """

    value = environment_variables.get(variable_name, "").strip()

    if not value:
        raise RuntimeError(
            f"Переменная окружения {variable_name} должна быть заполнена."
        )

    return value


def read_boolean(value_text: str) -> bool:
    """
    Преобразует текст в логическое значение.

    Распознаёт:
        - Истина: true, 1, yes, on
        - Ложь:   false, 0, no, off, пустая строка
    """

    normalized_value = value_text.strip().lower()

    true_values = {"true", "1", "yes", "on"}
    false_values = {"false", "0", "no", "off", ""}

    if normalized_value in true_values:
        return True

    if normalized_value in false_values:
        return False

    raise ValueError("Некорректное текстовое значение логического признака.")


def read_boolean_variable(variable_name: str, default_value: bool = False) -> bool:
    """
    Читает логическую переменную окружения.
    """

    return read_boolean(read_text(variable_name, str(default_value).lower()))


def read_list(source_text: str, separator_text: str = ",") -> list[str]:
    """
    Преобразует текст с разделителями в список непустых значений.
    """

    result_values = []

    for element_text in source_text.split(separator_text):
        cleaned_element_text = element_text.strip()

        if cleaned_element_text:
            result_values.append(cleaned_element_text)

    return result_values


def read_list_variable(
    variable_name: str,
    default_value: str = "",
    separator_text: str = ",",
) -> list[str]:
    """
    Читает переменную окружения со списком значений.
    """

    return read_list(read_text(variable_name, default_value), separator_text)


def read_integer(value_text: str, default_value: int = 0) -> int:
    """
    Преобразует текст в целое число.
    """

    cleaned_value = value_text.strip()

    if not cleaned_value:
        return default_value

    return int(cleaned_value)


def read_integer_variable(variable_name: str, default_value: int = 0) -> int:
    """
    Читает целочисленную переменную окружения.
    """

    return read_integer(read_text(variable_name), default_value)
