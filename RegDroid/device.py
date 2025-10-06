import subprocess
import os
import time
import re
from threading import Thread

import uiautomator2 as u2


class MyThread(Thread):
    def __init__(self, func, args):
        super(MyThread, self).__init__()
        self.func = func
        self.args = args

    def run(self):
        self.result = self.func(*self.args)

    def get_result(self):
        try:
            return self.result
        except Exception:
            return None


class Device(object):
    """
    Record the information of the device
    """

    def __init__(
        self, device_num=None, device_serial=None, is_emulator=True, rest_interval=None
    ):
        self.device_num = device_num
        self.device_serial = device_serial
        self.is_emulator = is_emulator
        self.use = None
        self.state = None
        self.last_state = None
        self.strategy = "screen"
        self.crash_logcat = ""
        self.last_crash_logcat = ""
        self.language = "en"
        self.rest_interval = rest_interval
        self.wifi_state = True
        self.gps_state = True
        self.sound_state = True
        self.battery_state = False
        self.game_mode = True
        self.blue_light = False
        self.notification = True
        self.permission = True
        self.hourformat = "12h"

    def set_strategy(self, strategy):
        self.strategy = strategy
        self.error_num = 0
        self.wrong_num = 0

    def set_thread(self, execute_event, args):
        # 如果已经有线程，先删除
        if hasattr(self, 'thread'):
            delattr(self, 'thread')
        if execute_event is not None:
            self.thread = MyThread(execute_event, args)
        else:
            self.thread = None

    def restart(self, emulator_path, emulator_name):
        try:
            # 提取端口号
            port_match = re.search(r'emulator-(\d+)', self.device_serial)
            if not port_match:
                raise ValueError(f"Invalid device serial: {self.device_serial}")
            
            port = port_match.group(1)
            print(f"Restarting emulator on port {port}")
            
            # 如果不是第一次，先关闭旧的模拟器
            if not first_time:
                try:
                    subprocess.run(
                        ["adb", "-s", self.device_serial, "emu", "kill"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=True,
                        timeout=10
                    )
                    print(f"Successfully sent kill command to {self.device_serial}")
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    print(f"Error killing emulator: {e}")
            
            # 启动新的模拟器
            emulator_cmd = [
                emulator_path,
                "-avd", emulator_name,
                "-read-only",
                "-port", port,
                "-no-window"
            ]
            print(f"Starting emulator: {' '.join(emulator_cmd)}")
            
            subprocess.Popen(
                emulator_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # 等待设备就绪 - 这个命令会阻塞直到设备可用
            print("Waiting for device...")
            subprocess.run(
                ["adb", "-s", self.device_serial, "wait-for-device"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=60
            )
            print("Device is ready")

            # 等待系统完全启动
            self._wait_for_boot_complete()
            
                
        except Exception as ex:
            print(f"Unexpected error restarting device {self.device_serial}: {ex}")

    def _wait_for_boot_complete(self, timeout=60):
        """等待系统启动完成"""
        print("Waiting for system boot to complete...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["adb", "-s", self.device_serial, "shell", "getprop", "sys.boot_completed"],
                    capture_output=True, text=True, timeout=5
                )
                
                if result.returncode == 0 and result.stdout.strip() == "1":
                    print("System boot completed")
                    return
                    
            except subprocess.TimeoutExpired:
                pass
            
            time.sleep(2)
        
        print(f"Warning: System boot may not be complete after {timeout}s")

    
    
    def make_strategy(self, root_path):
        start_time = time.time()
        if not os.path.isdir(f"{root_path}strategy_{self.strategy}/"):
            os.makedirs(f"{root_path}strategy_{self.strategy}/")
        self.f_error = open(
            f"{root_path}strategy_{self.strategy}/error_realtime.txt",
            'w',
            encoding='utf-8',
        )
        self.f_wrong = open(
            f"{root_path}strategy_{self.strategy}/wrong_realtime.txt",
            'w',
            encoding='utf-8',
        )
        end_time = time.time()
        print(f"make_strategy {self.device_serial} time: {end_time - start_time} seconds")

    def make_strategy_runcount(self, run_count, root_path):
        start_time = time.time()
        self.path = f"{root_path}strategy_{self.strategy}/{str(run_count)}/"
        if not os.path.isdir(self.path):
            os.makedirs(self.path)
        if not os.path.isdir(f"{self.path}screen/"):
            os.makedirs(f"{self.path}screen/")
        self.f_read_trace = open(f'{self.path}/read_trace.txt', 'w', encoding='utf-8')
        self.f_trace = open(f'{self.path}/trace.txt', 'w', encoding='utf-8')

        self.error_event_lists = []
        self.wrong_event_lists = []
        self.wrong_flag = True
        end_time = time.time()
        print(f"make_strategy_runcount {self.device_serial} time: {end_time - start_time} seconds")

    def connect(self):
        self.use = u2.connect_usb(self.device_serial)
        self.use.implicitly_wait(5.0)

    def install_app(self, app, app_object):
        start_time = time.time()
        print(app)
        subprocess.run(
            ["adb", "-s", self.device_serial, "install", "-g", app], stdout=subprocess.PIPE
        )

        # print("check permissions", app_object.permissions)
        # 对于特定的需要手动授权的权限，可以添加额外的授权命令
        special_permissions = []
        for permission in app_object.permissions:
            if app_object.package_name in permission:
                special_permissions.append(permission)
        
        for permission in special_permissions:
            try:
                subprocess.run(
                    ["adb", "-s", self.device_serial, "shell", "pm", "grant", 
                    app_object.package_name, permission],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True
                )
                print(f"Successfully granted permission: {permission}")
            except subprocess.CalledProcessError as e:
                print(f"Failed to grant permission {permission}: {e}")

        end_time = time.time()
        print(f"install_app {self.device_serial} time: {end_time - start_time} seconds")

    def initialization(self):
        self.use.set_orientation("n")

    def initial_setting(self):
        print("initial setting")

    def screenshot_and_getstate(self, path, event_count):
        self.screenshot_path = (
            path + str(event_count) + '_' + self.device_serial + '.png'
        )
        self.use.screenshot(path + str(event_count) + '_' + self.device_serial + '.png')
        xml = self.use.dump_hierarchy()
        f = open(
            path + str(event_count) + '_' + self.device_serial + '.xml',
            'w',
            encoding='utf-8',
        )
        f.write(xml)
        with open(
            path + str(event_count) + '_' + self.device_serial + '.xml',
            'r',
            encoding='utf-8',
        ) as f:
            lines = f.readlines()
        return lines

    def update_state(self, state):
        self.last_state = self.state
        self.state = state

    def stop_app(self, app):
        self.use.app_stop(app.package_name)

    def clear_app(self, app, is_login_app):
        if is_login_app == 0:
            self.use.app_stop(app.package_name)
        else:
            self.use.app_clear(app.package_name)

    def start_app(self, app):
        # 启动应用
        subprocess.run(
            [
                "adb",
                "-s",
                self.device_serial,
                "shell",
                "am",
                "start",
                "-n",
                f"{app.package_name}/{app.main_activity}",
            ],
            stdout=subprocess.PIPE,
        )
        
        # # 尝试跳过欢迎页面
        # try:
        #     # 等待应用启动
        #     time.sleep(2)
            
        #     # 尝试跳过欢迎页面
        #     self.skip_welcome(app.package_name)
        # except Exception as e:
        #     print(f"Error during welcome page skip for {app.package_name}: {e}")
        
        # # self.use.app_wait(app.package_name, front=True, timeout=2.0)
        return True

    def click(self, view, strategy_list):
        try:
            if self.strategy != "language":
                if view.description != "":
                    self.use(
                        description=view.description, packageName=view.package
                    ).click()
                    return "description"
                elif view.text != "":
                    self.use(text=view.text, packageName=view.package).click()
                    return "text"
                else:
                    self.use(
                        className=view.className,
                        resourceId=view.resourceId,
                        instance=view.instance
                    ).click()
                    return "classNameresourceId"
                
            elif view.instance == 0:
                self.use(
                    className=view.className,
                    resourceId=view.resourceId,
                    packageName=view.package,
                ).click()
                return "classNameresourceId"
            else:
                self.use.click(view.x, view.y)
                return "xy"
        except:
            self.use.click(view.x, view.y)
            return "xy"

    def _click(self, view, text):
        try:
            if text is not None and view.text == text:
                self.use(text=view.text, packageName=view.package).click()
                return "text"
            if view.description != "":
                self.use(description=view.description, packageName=view.package).click()
                return "description"
            elif view.instance == 0:
                self.use(
                    className=view.className,
                    resourceId=view.resourceId,
                    packageName=view.package,
                ).click()
                return "classNameresourceId"
            else:
                self.use.click(view.x, view.y)
                return "xy"
        except:
            self.use.click(view.x, view.y)
            return "xy"

    def longclick(self, view, strategy_list):
        try:
            if self.strategy != "language":
                if view.description != "":
                    self.use(
                        description=view.description, packageName=view.package
                    ).long_click(duration=2.0)
                    return
                elif view.text != "":
                    self.use(text=view.text, packageName=view.package).long_click(
                        duration=2.0
                    )
                    return
                elif view.instance == 0:
                    self.use(
                        className=view.className,
                        resourceId=view.resourceId,
                        packageName=view.package,
                    ).long_click(duration=2.0)
                else:
                    self.use.long_click(view.x, view.y, duration=2.0)
            elif view.instance == 0:
                self.use(
                    className=view.className,
                    resourceId=view.resourceId,
                    packageName=view.package,
                ).long_click(duration=2.0)
            else:
                self.use.long_click(view.x, view.y, duration=2.0)
        except:
            self.use.long_click(view.x, view.y, duration=2.0)
            # print("x:"+str(view.x)+",y:"+str(view.y))
            return

    def edit(self, view, strategy_list, text):
        if "language" not in strategy_list:
            self.use(
                className=view.className,
                resourceId=view.resourceId,
                packageName=view.package,
            ).set_text(text)
        else:
            self.use(
                className=view.className,
                resourceId=view.resourceId,
                packageName=view.package,
            ).set_text(text)

    def scroll(self, view, strategy_list):
        if view.action == "scroll_backward":
            self.use(
                className=view.className,
                resourceId=view.resourceId,
                packageName=view.package,
            ).scroll.vert.backward(steps=100)
        elif view.action == "scroll_forward":
            self.use(
                className=view.className,
                resourceId=view.resourceId,
                packageName=view.package,
            ).scroll.vert.forward(steps=100)
        elif view.action == "scroll_right":
            self.use(
                className=view.className,
                resourceId=view.resourceId,
                packageName=view.package,
            ).scroll.horiz.toEnd(max_swipes=10)
        elif view.action == "scroll_left":
            self.use(
                className=view.className,
                resourceId=view.resourceId,
                packageName=view.package,
            ).scroll.horiz.toBeginning(max_swipes=10)

    def close_keyboard(self):
        subprocess.run(
            ["adb", "-s", self.device_serial, "shell", "input", "keyevent", "111"],
            stdout=subprocess.PIPE,
        )

    def add_file(self, resource_path, resource, path):
        subprocess.run(
            ["adb", "-s", self.device_serial, "logcat", "-c"], stdout=subprocess.PIPE
        )
        subprocess.run(
            [
                "adb",
                "-s",
                self.device_serial,
                "push",
                f"{resource_path}/{resource}",
                path,
            ],
            stdout=subprocess.PIPE,
        )

    def log_crash(self, path):
        os.popen(f"adb -s {self.device_serial} logcat -b crash >{path}")

    def mkdir(self, path):
        subprocess.run(
            ["adb", "-s", self.device_serial, "shell", "mkdir", path],
            stdout=subprocess.PIPE,
        )

    def disable_keyboard(self):
        self.use.set_fastinput_ime(True)

    def skip_welcome(self, app_package=None):
        """
        尝试跳过应用的欢迎页面
        :param app_package: 应用的包名，如果为 None 则使用当前应用
        :return: 是否成功跳过欢迎页

        需要case by case 处理
        """
        # 确保设备已连接
        if self.use is None:
            self.connect()

        if app_package == "it.feio.android.omninotes" or app_package == "net.gsantner.markor":
            print("debug skip_omninotes_welcome")
            self.skip_omninotes_welcome()
        elif app_package == "com.ichi2.anki":
            print("debug skip_anki_welcome")
            self.skip_anki_welcome()
        else:
            return

    def skip_anki_welcome(self):
        """
        Skip the Anki welcome/onboarding screens

        Steps:
        //*[@resource-id="com.ichi2.anki:id/get_started"]
        //*[@resource-id="com.ichi2.anki:id/switch_widget"]
        ALLOW
        //*[@resource-id="com.ichi2.anki:id/continue_button"]
        Back
        """
        try:
            start_time = time.time()
            # Maximum number of attempts to prevent infinite loop
            max_attempts = 6
            current_attempt = 0

            # Step 1: Click "Get Started"
            get_started_button = self.use(resourceId="com.ichi2.anki:id/get_started")
            if get_started_button.exists():
                get_started_button.click()
                time.sleep(1)
                current_attempt += 1

            # Step 2: Click "Switch Widget"
            switch_widget_button = self.use(resourceId="com.ichi2.anki:id/switch_widget")
            if switch_widget_button.exists():
                switch_widget_button.click()
                time.sleep(1)
                current_attempt += 1

            # Step 3: Handle permission dialogs
            permission_texts = ["OK", "ALLOW", "允许", "确定"]
            for text in permission_texts:
                permission_button = self.use(text=text)
                if permission_button.exists():
                    permission_button.click()
                    time.sleep(1)
                    current_attempt += 1
                    break

            # Step 4: Click "Continue"
            continue_button = self.use(resourceId="com.ichi2.anki:id/continue_button")
            if continue_button.exists():
                continue_button.click()
                time.sleep(1)
                current_attempt += 1

            # Step 5: Press Back
            self.use.press("back")
            time.sleep(1)
            current_attempt += 1

            end_time = time.time()
            print(f"skip_anki_welcome time: {end_time - start_time} seconds")

            if current_attempt > 0:
                print(f"Completed Anki welcome page skip after {current_attempt} steps")
                return True
            else:
                print("Unable to skip Anki welcome page")
                return False

        except Exception as e:
            print(f"Error during Anki welcome screen skip: {e}")
            return False

    def skip_omninotes_welcome(self):
        """
        Skip the OmniNotes welcome/onboarding screens
        
        Steps:
        1. Repeatedly click the 'next' button
            # //*[@resource-id="it.feio.android.omninotes:id/next"]
        2. Finally click the 'done' button to complete onboarding
            # //*[@resource-id="it.feio.android.omninotes:id/done"]
        """
        try:
            max_attempts = 8
            current_attempt = 0
            
            while current_attempt < max_attempts:
                print(f"Skip welcome attempt {current_attempt + 1}")
                
                # 模糊查找包含 'next' 的资源 ID
                next_buttons = self.use(resourceIdMatches=".*next")
                # 模糊查找包含 'done' 的资源 ID
                done_buttons = self.use(resourceIdMatches=".*done")
                
                print(f"Next buttons found: {next_buttons.count}")
                print(f"Done buttons found: {done_buttons.count}")
                
                # 优先处理 'next' 按钮
                if next_buttons.count > 0:
                    print("Clicking 'next' button")
                    next_buttons[0].click()
                    time.sleep(1)  # 增加等待时间
                    current_attempt += 1
                    continue
                
                # 如果找到 'done' 按钮
                if done_buttons.count > 0:
                    print("Clicking 'done' button")
                    done_buttons[0].click()
                    time.sleep(1)
                    return True  # 成功跳过
                
                # 如果没有找到任何按钮，等待并重试
                time.sleep(1)
                current_attempt += 1
            
            print("Failed to skip welcome screen")
            return False
        except Exception as e:
            print(f"Error during OmniNotes welcome screen skip: {e}")
            return False
