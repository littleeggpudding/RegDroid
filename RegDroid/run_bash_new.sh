#!/bin/bash
export ANDROID_HOME=~/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$PATH
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH=$PATH:$ANDROID_HOME/emulator

MAX_RUNS=20
COUNT=1
OUTPUT_BASE="/data/shiwensong/RegDroid/Output/com.amaze.filemanager"

while [ $COUNT -le $MAX_RUNS ]; do
    echo "===== Run $COUNT started at $(date) ====="
    source ~/.bashrc

    # 激活虚拟环境
    source /home/shiwensong/.virtualenvs/RegDroid/bin/activate

    python3 start.py \
      -base_app_path ./App/AmazeFileManager_3.6.1.apk \
      -new_app_dir ./AmazeFileManager_8/ \
      -output test-results \
      -testcase_count 30 \
      -event_num 110 \
      -emulator_name Android8.0 \
      > start_$COUNT.log 2>&1 &

    PID=$!
    echo "Started process with PID $PID"

    # 等待这个进程结束
    wait $PID
    echo "Run $COUNT finished at $(date)"

    # 如果输出目录存在，则重命名
    if [ -d "$OUTPUT_BASE" ]; then
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        mv "$OUTPUT_BASE" "${OUTPUT_BASE}_${TIMESTAMP}"
        echo "Renamed output folder to ${OUTPUT_BASE}_${TIMESTAMP}"
    else
        echo "Warning: $OUTPUT_BASE not found, skipping rename"
    fi

    COUNT=$((COUNT + 1))
done

echo "===== All $MAX_RUNS runs completed ====="