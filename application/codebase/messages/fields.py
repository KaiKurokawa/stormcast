"""
Поля Django для нативных типов PostgreSQL, отсутствующих среди стандартных
типов полей ORM.
"""

from django.db import models


class PostgreSQLEnumField(models.CharField):
    """
    Поле CharField, использующее именованный перечисляемый тип PostgreSQL.

    Поле сохраняет поведение CharField на уровне Django, включая choices
    и преобразование значений, но указывает PostgreSQL на существующий
    пользовательский тип вместо VARCHAR.

    Тип PostgreSQL должен быть создан до применения миграции,
    создающей таблицу с этим полем.
    """

    def __init__(self, *args, enum_type: str, **kwargs) -> None:
        """
        Инициализирует поле с именем типа PostgreSQL.

        Arguments:
            enum_type: Полностью квалифицированное имя типа PostgreSQL,
                например '"messages"."message_type"'.
        """
        self.enum_type = enum_type
        super().__init__(*args, **kwargs)

    def db_type(self, connection) -> str | None:
        """
        Возвращает тип столбца для используемой базы данных.

        Arguments:
            connection: Соединение Django с базой данных.

        Returns:
            str | None: Имя типа PostgreSQL или тип CharField для другой СУБД.
        """
        if connection.vendor == "postgresql":
            return self.enum_type

        return super().db_type(connection)

    def deconstruct(self):
        """
        Возвращает параметры, необходимые для сериализации поля в миграции.

        Returns:
            tuple: Имя поля, путь импорта, позиционные и именованные аргументы.
        """
        name, path, arguments, keyword_arguments = super().deconstruct()
        keyword_arguments["enum_type"] = self.enum_type

        return name, path, arguments, keyword_arguments
