#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_CURRENT="$(mktemp "${TMPDIR:-/tmp}/noc-cron-current.XXXXXX")"
TMP_NEXT="$(mktemp "${TMPDIR:-/tmp}/noc-cron-next.XXXXXX")"
trap 'rm -f "$TMP_CURRENT" "$TMP_NEXT"' EXIT HUP INT TERM

PEDIDOS_BEGIN="# BEGIN Codex Monitor Pedidos Pleno"
PEDIDOS_END="# END Codex Monitor Pedidos Pleno"
PROMO_BEGIN="# BEGIN Codex Monitor Promocao Precos"
PROMO_END="# END Codex Monitor Promocao Precos"
RESOURCE_BEGIN="# BEGIN Codex Monitor Recursos Processos"
RESOURCE_END="# END Codex Monitor Recursos Processos"
ESTOQUE_RELEX_BEGIN="# BEGIN Codex Monitor Estoque RELEX"
ESTOQUE_RELEX_END="# END Codex Monitor Estoque RELEX"
RETIFICACAO_RET_BEGIN="# BEGIN Codex Monitor Retificacao RET"
RETIFICACAO_RET_END="# END Codex Monitor Retificacao RET"
ALERT_BEGIN="# BEGIN Codex Alertas Telegram NOC"
ALERT_END="# END Codex Alertas Telegram NOC"
WATCH_BEGIN="# BEGIN Codex Watch Promocao Precos Ate OK"
WATCH_END="# END Codex Watch Promocao Precos Ate OK"

PEDIDOS_RUNNER="$ROOT_DIR/scripts/run_pedidos_business_monitor_step.sh"
PEDIDOS_WATCHER="$ROOT_DIR/scripts/watch_pedidos_until_ok.py"
PROMO_RUNNER="$ROOT_DIR/scripts/update_promopreco_monitor.py"
PROMO_WATCHER="$ROOT_DIR/scripts/watch_promopreco_until_ok.py"
RESOURCE_RUNNER="$ROOT_DIR/scripts/update_process_resource_monitor.py"
ESTOQUE_RELEX_RUNNER="$ROOT_DIR/scripts/update_estoque_relex_monitor.py"
RETIFICACAO_RET_RUNNER="$ROOT_DIR/scripts/update_retificacao_ret_monitor.py"
ALERT_RUNNER="$ROOT_DIR/scripts/alert_telegram_monitor.py"
PEDIDOS_LOG="$ROOT_DIR/outputs/pleno_business_monitor/logs/pedidos_cron.log"
PROMO_LOG="$ROOT_DIR/outputs/pleno_business_monitor/logs/promopreco_cron.log"
RESOURCE_LOG="$ROOT_DIR/outputs/pleno_business_monitor/logs/process_resources_cron.log"
ESTOQUE_RELEX_LOG="$ROOT_DIR/outputs/pleno_business_monitor/logs/estoque_relex_cron.log"
RETIFICACAO_RET_LOG="$ROOT_DIR/outputs/pleno_business_monitor/logs/retificacao_ret_cron.log"
ALERT_LOG="$ROOT_DIR/outputs/pleno_business_monitor/logs/telegram_alert.log"

if crontab -l > "$TMP_CURRENT" 2>/dev/null; then
  awk \
    -v pb="$PEDIDOS_BEGIN" -v pe="$PEDIDOS_END" \
    -v mb="$PROMO_BEGIN" -v me="$PROMO_END" \
    -v rb="$RESOURCE_BEGIN" -v re="$RESOURCE_END" \
    -v eb="$ESTOQUE_RELEX_BEGIN" -v ee="$ESTOQUE_RELEX_END" \
    -v tb="$RETIFICACAO_RET_BEGIN" -v te="$RETIFICACAO_RET_END" \
    -v ab="$ALERT_BEGIN" -v ae="$ALERT_END" \
    -v wb="$WATCH_BEGIN" -v we="$WATCH_END" '
      $0 == pb || $0 == mb || $0 == rb || $0 == eb || $0 == tb || $0 == ab || $0 == wb { skip = 1; next }
      $0 == pe || $0 == me || $0 == re || $0 == ee || $0 == te || $0 == ae || $0 == we { skip = 0; next }
      skip != 1 { print }
    ' "$TMP_CURRENT" > "$TMP_NEXT"
else
  : > "$TMP_NEXT"
fi

append_header() {
  printf "\n%s\n" "$1" >> "$TMP_NEXT"
  printf "SHELL=/bin/sh\n" >> "$TMP_NEXT"
  printf "PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin\n" >> "$TMP_NEXT"
}

append_monitored_job() {
  minute="$1"
  hour="$2"
  command="$3"
  log="$4"
  alert_args="${5:-}"
  printf "%s %s * * * cd %s && %s >> %s 2>&1; cd %s && python3 %s %s >> %s 2>&1\n" \
    "$minute" "$hour" "$ROOT_DIR" "$command" "$log" "$ROOT_DIR" "$ALERT_RUNNER" "$alert_args" "$ALERT_LOG" >> "$TMP_NEXT"
}

append_alert_job() {
  minute="$1"
  hour="$2"
  alert_args="$3"
  printf "%s %s * * * cd %s && python3 %s %s >> %s 2>&1\n" \
    "$minute" "$hour" "$ROOT_DIR" "$ALERT_RUNNER" "$alert_args" "$ALERT_LOG" >> "$TMP_NEXT"
}

append_header "$PEDIDOS_BEGIN"
printf "50 7 * * * cd %s && python3 %s --block entrada --until 09:30 --interval-seconds 600 >> %s 2>&1\n" \
  "$ROOT_DIR" "$PEDIDOS_WATCHER" "$PEDIDOS_LOG" >> "$TMP_NEXT"
printf "10 8 * * * cd %s && %s check_0810 >> %s 2>&1; cd %s && python3 %s --force >> %s 2>&1\n" \
  "$ROOT_DIR" "$PEDIDOS_RUNNER" "$PEDIDOS_LOG" "$ROOT_DIR" "$ALERT_RUNNER" "$ALERT_LOG" >> "$TMP_NEXT"
printf "30 9 * * * cd %s && python3 %s --block relex --until 10:00 --interval-seconds 60 >> %s 2>&1\n" \
  "$ROOT_DIR" "$PEDIDOS_WATCHER" "$PEDIDOS_LOG" >> "$TMP_NEXT"
printf "35 9 * * * cd %s && %s remote >> %s 2>&1; cd %s && python3 %s >> %s 2>&1\n" \
  "$ROOT_DIR" "$PEDIDOS_RUNNER" "$PEDIDOS_LOG" "$ROOT_DIR" "$ALERT_RUNNER" "$ALERT_LOG" >> "$TMP_NEXT"
printf "55 9 * * * cd %s && %s remote >> %s 2>&1; cd %s && python3 %s >> %s 2>&1\n" \
  "$ROOT_DIR" "$PEDIDOS_RUNNER" "$PEDIDOS_LOG" "$ROOT_DIR" "$ALERT_RUNNER" "$ALERT_LOG" >> "$TMP_NEXT"
printf "%s\n" "$PEDIDOS_END" >> "$TMP_NEXT"

append_header "$PROMO_BEGIN"
printf "30 4 * * * cd %s && python3 %s --run-time 04:30 --until 06:30 >> %s 2>&1\n" \
  "$ROOT_DIR" "$PROMO_WATCHER" "$PROMO_LOG" >> "$TMP_NEXT"
printf "30 6 * * * cd %s && python3 %s --run-time 06:30 --until 09:00 >> %s 2>&1\n" \
  "$ROOT_DIR" "$PROMO_WATCHER" "$PROMO_LOG" >> "$TMP_NEXT"
append_alert_job 5 7 "--force"
printf "%s\n" "$PROMO_END" >> "$TMP_NEXT"

append_header "$RESOURCE_BEGIN"
printf "*/5 4-9 * * * cd %s && python3 %s >> %s 2>&1\n" \
  "$ROOT_DIR" "$RESOURCE_RUNNER" "$RESOURCE_LOG" >> "$TMP_NEXT"
printf "%s\n" "$RESOURCE_END" >> "$TMP_NEXT"

append_header "$ESTOQUE_RELEX_BEGIN"
append_monitored_job 30 5 "python3 $ESTOQUE_RELEX_RUNNER" "$ESTOQUE_RELEX_LOG" "--only-errors --scope estoque-retificacao"
printf "%s\n" "$ESTOQUE_RELEX_END" >> "$TMP_NEXT"

append_header "$RETIFICACAO_RET_BEGIN"
printf "0 * * * * cd %s && python3 %s >> %s 2>&1; cd %s && python3 %s --only-errors >> %s 2>&1\n" \
  "$ROOT_DIR" "$RETIFICACAO_RET_RUNNER" "$RETIFICACAO_RET_LOG" "$ROOT_DIR" "$ALERT_RUNNER" "$ALERT_LOG" >> "$TMP_NEXT"
printf "%s\n" "$RETIFICACAO_RET_END" >> "$TMP_NEXT"

crontab "$TMP_NEXT"
echo "Crontab NOC instalada: pedidos, promocao/precos, estoque RELEX, alertas de erro na madrugada e resumo apos 7h."
