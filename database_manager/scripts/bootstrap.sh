#!/bin/sh
set -e

# Рабочий каталог (именованный том)
WORK_DIR="/var/lib/pgadmin"

# Оригинальный entrypoint pgAdmin ищет файл серверов именно по этому пути
SERVERS_JSON="/pgadmin4/servers.json"
PGPASS_FILE="/pgadmin4/pgpass"

# Если внутренняя база данных pgAdmin уже существует, импорт серверов не нужен.
# Но мы всё равно гарантируем правильные права на рабочий каталог.
if [ -f "$WORK_DIR/pgadmin4.db" ]; then
    chown -R 5050:5050 "$WORK_DIR"
    exit 0
fi

# Подстановка значений по умолчанию
: "${DATABASE__INTERFACE__HOSTNAME:=database}"
: "${DATABASE__INTERFACE__PORT__CONTAINER:=5432}"
: "${DATABASE__GENERAL__NAME:=postgres}"
: "${DATABASE__CREDENTIALS__DEFAULT__USERNAME:=postgres}"
: "${DATABASE__CREDENTIALS__DEFAULT__PASSWORD:=postgres}"

# Генерация файла конфигурации серверов
cat > "$SERVERS_JSON" <<EOF
{
  "Servers": {
    "1": {
      "Name": "Database",
      "Group": "Servers",
      "Host": "$DATABASE__INTERFACE__HOSTNAME",
      "Port": $DATABASE__INTERFACE__PORT__CONTAINER,
      "MaintenanceDB": "$DATABASE__GENERAL__NAME",
      "Username": "$DATABASE__CREDENTIALS__DEFAULT__USERNAME",
      "SSLMode": "prefer",
      "PassFile": "$PGPASS_FILE"
    }
  }
}
EOF

# Генерация файла паролей
printf '%s:%s:*:%s:%s\n' \
  "$DATABASE__INTERFACE__HOSTNAME" \
  "$DATABASE__INTERFACE__PORT__CONTAINER" \
  "$DATABASE__CREDENTIALS__DEFAULT__USERNAME" \
  "$DATABASE__CREDENTIALS__DEFAULT__PASSWORD" > "$PGPASS_FILE"

# Назначение владельца и прав доступа
chown 5050:5050 "$SERVERS_JSON" "$PGPASS_FILE"
chmod 644 "$SERVERS_JSON"
chmod 600 "$PGPASS_FILE"

# Гарантируем, что рабочий каталог принадлежит pgadmin
chown -R 5050:5050 "$WORK_DIR"
