1. System Path

1.1 vim ~/.bashrc

1.2 ctrl c+ ctrl v:

export JAVA_HOME=$HOME/jdk/jdk-17.0.12
export PATH=$JAVA_HOME/bin:$PATH
# Android SDK
export ANDROID_HOME=$HOME/android-sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME

# Add Android tools to PATH
export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$PATH
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH=$PATH:$ANDROID_HOME/emulator


2. Install Java

2.1 Downdoad and unzip:
mkdir -p ~/jdk
curl -O https://download.oracle.com/java/17/archive/jdk-17.0.12_linux-x64_bin.tar.gz
tar -xzvf jdk-17.0.12_linux-x64_bin.tar.gz -C ~/jdk
rm -rf jdk-17.0.12_linux-x64_bin.tar.gz

2.2 Check:
ls ~/jdk/jdk-17.0.12/bin/java

3. Android SDK

3.1 Install sdkmanager 
mkdir -p ~/android-sdk
curl -L -o commandlinetools-linux_latest.zip "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip?hl=zh-cn"
unzip commandlinetools-linux_latest.zip -d ~/android-sdk/cmdline-tools
rm commandlinetools-linux_latest.zip
mkdir -p ~/android-sdk/cmdline-tools/latest
mv ~/android-sdk/cmdline-tools/cmdline-tools/* ~/android-sdk/cmdline-tools/latest/
rm -rf ~/android-sdk/cmdline-tools/cmdline-tools

3.2 Install other tools
yes | sdkmanager --licenses
sdkmanager "platform-tools" "emulator"
sdkmanager "platforms;android-26" "system-images;android-26;google_apis;x86"

3.3 Check:
ls ~/android-sdk/
Output: cmdline-tools  emulator  licenses  platforms  platform-tools  system-images

3.4 Creat a emulator 
avdmanager create avd --force --name Android8.0 --package 'system-images;android-26;google_apis;x86' --abi google_apis/x86 --sdcard 512M --device "pixel_xl"

4. Test environment

emulator -avd Android8.0 -read-only -port 5554 -no-window