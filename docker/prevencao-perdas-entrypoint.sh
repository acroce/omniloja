#!/bin/sh
set -eu

mkdir -p /app/outputs/prevencao_perdas /app/.cache
ln -snf "/usr/share/zoneinfo/${TZ:-America/Sao_Paulo}" /etc/localtime
printf '%s\n' "${TZ:-America/Sao_Paulo}" > /etc/timezone

printf '%s\n' \
  'SHELL=/bin/sh' \
  'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  "${PREV_PERDAS_CRON:-0 9,15 * * *} root /app/scripts/run-prevencao-perdas-cron.sh" \
  > /etc/cron.d/prevencao-perdas
chmod 0644 /etc/cron.d/prevencao-perdas
cron

exec node /app/audit-web/server.mjs
