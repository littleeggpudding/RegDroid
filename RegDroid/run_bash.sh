#!/bin/bash
export ANDROID_HOME=~/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$PATH
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator

OUTPUT_BASE="/data/shiwensong/RegDroid/Output/it.feio.android.omninotes"
CSV_FILE="./select_apks/it.feio.android.omninotes_0.csv"
APPS_LOG_FILE="./apps_test_log_$(date +%Y%m%d_%H%M%S).txt"
TEMP_NEW_APP_DIR=$(mktemp -d)

# 读取 CSV 第7列为 APK 文件名（跳过表头）
mapfile -t APPS < <(tail -n +2 "$CSV_FILE" | awk -F',' '{print $7}')

# 初始化日志
echo "Apps Test Log" > "$APPS_LOG_FILE"
echo "==============" >> "$APPS_LOG_FILE"

# 定义测试函数
run_tests() {
    local BASE_APP="$1"
    shift
    local NEW_APPS=("$@")

    if [ ${#NEW_APPS[@]} -eq 0 ]; then
        echo "No new apps left to test for base $BASE_APP"
        return 1
    fi

    local BASE_APP_PATH="./select_apks/it.feio.android.omninotes/${BASE_APP}"

    echo "===== Run with base: $BASE_APP ====="
    echo "Base App: ${BASE_APP}" >> "$APPS_LOG_FILE"
    echo "New Apps:" >> "$APPS_LOG_FILE"
    printf '%s\n' "${NEW_APPS[@]}" >> "$APPS_LOG_FILE"
    echo "---" >> "$APPS_LOG_FILE"

    # 清空临时目录并复制新 app
    rm -f "$TEMP_NEW_APP_DIR"/*
    for new_app in "${NEW_APPS[@]}"; do
        cp "./select_apks/it.feio.android.omninotes/${new_app}" "$TEMP_NEW_APP_DIR/"
    done

    # 启动测试
    source /home/shiwensong/.virtualenvs/RegDroid/bin/activate
    python3 start.py \
      -base_app_path "$BASE_APP_PATH" \
      -new_app_dir "$TEMP_NEW_APP_DIR" \
      -output test-results \
      -testcase_count 30 \
      -event_num 110 \
      -emulator_name Android10.0 \
      > "start_${BASE_APP}.log" 2>&1

    # 重命名输出目录
    if [ -d "$OUTPUT_BASE" ]; then
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        RENAMED_OUTPUT_BASE="${OUTPUT_BASE}_${BASE_APP}_${TIMESTAMP}"
        mv "$OUTPUT_BASE" "$RENAMED_OUTPUT_BASE"
        echo "Renamed output folder to $RENAMED_OUTPUT_BASE" >> "$APPS_LOG_FILE"
        echo "Renamed output folder to $RENAMED_OUTPUT_BASE"
    else
        echo "Warning: $OUTPUT_BASE not found, skipping rename" >> "$APPS_LOG_FILE"
        echo "Warning: $OUTPUT_BASE not found, skipping rename"
    fi
}

# 主循环
while [ ${#APPS[@]} -gt 1 ]; do
    # base = 最后一个
    BASE_APP="${APPS[-1]}"
    # new = base 之前的所有
    NEW_APPS=("${APPS[@]:0:${#APPS[@]}-1}")

    run_tests "$BASE_APP" "${NEW_APPS[@]}" || break

    # 移除 base（即最后一个）
    unset 'APPS[-1]'
done

rmdir "$TEMP_NEW_APP_DIR"

echo "===== All apps tested ====="
echo "Apps test log saved to $APPS_LOG_FILE"
