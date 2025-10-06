pkill -f "qemu-system-i386-headless"
pkill -f "emulator"
ps -ef | grep "python start.py" | grep -v grep
ps -ef | grep qemu-system | grep -v grep
