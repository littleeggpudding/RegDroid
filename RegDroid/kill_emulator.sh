#!/bin/bash
# 批量关闭所有正在运行的 Android Emulator

# 列出所有 emulator 设备
emulators=$(adb devices | awk '/emulator-/{print $1}')

if [ -z "$emulators" ]; then
  echo "✅ 没有发现运行中的 emulator"
  exit 0
fi

echo "发现以下 emulator，将逐个关闭："
echo "$emulators"

# 优雅关闭
for serial in $emulators; do
  echo "→ 关闭 $serial ..."
  adb -s $serial emu kill
done

echo "✅ 所有 emulator 已关闭"
