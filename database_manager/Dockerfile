FROM dpage/pgadmin4:9.17

USER root

# Копирование скриптов инициализации и точки входа
COPY scripts/bootstrap.sh /usr/local/bin/bootstrap.sh
COPY scripts/entrypoint.sh /usr/local/bin/custom-entrypoint.sh

# Предоставление прав на выполнение
RUN chmod +x /usr/local/bin/bootstrap.sh \
 && chmod +x /usr/local/bin/custom-entrypoint.sh

# Точка входа переопределяет стандартное поведение.
ENTRYPOINT ["/usr/local/bin/custom-entrypoint.sh"]
