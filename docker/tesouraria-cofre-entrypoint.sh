#!/bin/sh
set -eu

mkdir -p /app/outputs/tesouraria_cofre_inteligente /app/.cache
ln -snf "/usr/share/zoneinfo/${TZ:-America/Sao_Paulo}" /etc/localtime
printf '%s\n' "${TZ:-America/Sao_Paulo}" > /etc/timezone

printf '%s\n' \
  'SHELL=/bin/sh' \
  'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
  'TESOURARIA_ROOT=/app' \
  'TESOURARIA_LOCK_FILE=/app/outputs/tesouraria_cofre_inteligente/tesouraria.lock' \
  '0 8,14,17 * * * root /app/scripts/run-tesouraria-cofre-cron.sh' \
  > /etc/cron.d/tesouraria-cofre
chmod 0644 /etc/cron.d/tesouraria-cofre
cron

exec node /app/audit-web/server.mjs
