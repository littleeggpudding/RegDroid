CHECK_INTERVAL="${CHECK_INTERVAL:-60}"     # 检查频率（秒）

echo "[INFO] TEST monitor started. LOG_DIR=$LOG_DIR, STALE_SECONDS=$STALE_SECONDS, PROC_PATTERN=$PROC_PATTERN, LOG_PATTERN=$LOG_PATTERN, CHECK_INTERVAL=$CHECK_INTERVAL"

while true; do
  PIDS="$(pgrep -f "$PROC_PATTERN" || true)"
  if [[ -z "$PIDS" ]]; then
    echo "$(date '+%F %T') [INFO] $PROC_PATTERN not running"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  LATEST_LOG="$(ls -1t "$LOG_DIR"/$LOG_PATTERN 2>/dev/null | head -n 1 || true)"
  if [[ -z "${LATEST_LOG}" ]]; then
    echo "$(date '+%F %T') [WARN] no log files found: $LOG_DIR/$LOG_PATTERN"
    sleep "$CHECK_INTERVAL"
    continue
  fi

  if stat --version >/dev/null 2>&1; then
    MTIME_EPOCH="$(stat -c %Y "$LATEST_LOG")"
  else
    MTIME_EPOCH="$(stat -f %m "$LATEST_LOG")"
  fi
  NOW_EPOCH="$(date +%s)"
  AGE=$((NOW_EPOCH - MTIME_EPOCH))

  if (( AGE > STALE_SECONDS )); then
    echo "$(date '+%F %T') [ALERT] stale log: $LATEST_LOG age=${AGE}s > ${STALE_SECONDS}s. (Would kill PIDs: $PIDS)"
    kill $PIDS
    kill -9 $PIDS
  else
    echo "$(date '+%F %T') [OK] log fresh: $LATEST_LOG age=${AGE}s"
  fi

  sleep "$CHECK_INTERVAL"
done