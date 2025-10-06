import os
import threading
import time
import subprocess
from injector import Injector
from policy import RandomPolicy
from state import State
from checker import Checker
from event import Event
from view import View
from utils import Utils
from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures


class Executor(object):
    def __init__(
        self,
        devices,
        app,
        app_path,
        strategy_list,
        pro_click,
        pro_longclick,
        pro_scroll,
        pro_home,
        pro_edit,
        pro_naturalscreen,
        pro_leftscreen,
        pro_back,
        pro_splitscreen,
        emulator_path,
        android_system,
        root_path,
        resource_path,
        testcase_count,
        start_testcase_count,
        event_num,
        timeout,
        policy_name,
        setting_random_denominator,
        serial_or_parallel,
        emulator_name,
        is_login_app,
        rest_interval,
        trace_path,
        choice,
    ):

        self.policy_name = policy_name
        self.timeout = timeout
        self.pro_click = pro_click
        self.pro_longclick = pro_longclick
        self.pro_scroll = pro_scroll
        self.pro_home = pro_home
        self.pro_edit = pro_edit
        self.pro_naturalscreen = pro_naturalscreen
        self.pro_leftscreen = pro_leftscreen
        self.pro_back = pro_back
        self.pro_splitscreen = pro_splitscreen
        self.app = app
        self.app_path = app_path
        self.devices = devices
        self.emulator_path = emulator_path
        self.android_system = android_system
        self.resource_path = resource_path
        self.strategy_list = strategy_list
        self.testcase_count = testcase_count
        self.start_testcase_count = start_testcase_count
        self.event_num = event_num
        self.setting_random_denominator = setting_random_denominator
        self.root_path = root_path
        self.policy = self.get_policy()
        self.serial_or_parallel = serial_or_parallel
        self.emulator_name = emulator_name
        self.is_login_app = is_login_app
        self.rest_interval = rest_interval
        self.guest_devices = self.devices[1:]
        self.trace_path = trace_path
        self.choice = choice
        self.deduplicate_list1 = []
        self.deduplicate_lists = [[] for _ in range(len(self.devices)-1)]  # 其他设备
        self.injector = Injector(
            devices=devices,
            app=app,
            strategy_list=strategy_list,
            emulator_path=emulator_path,
            android_system=android_system,
            root_path=root_path,
            resource_path=resource_path,
            testcase_count=testcase_count,
            event_num=event_num,
            timeout=timeout,
            setting_random_denominator=setting_random_denominator,
            rest_interval=rest_interval,
            choice=choice,
        )

        self.checker = Checker(
            devices=devices,
            app=app,
            strategy_list=strategy_list,
            emulator_path=emulator_path,
            android_system=android_system,
            root_path=root_path,
            resource_path=resource_path,
            testcase_count=testcase_count,
            event_num=event_num,
            timeout=timeout,
            setting_random_denominator=setting_random_denominator,
            rest_interval=rest_interval,
            choice=self.choice,
        )

        self.utils = Utils(devices=devices)

        # 添加 last_event 属性
        self.last_event = None

    def get_policy(self):
        if self.policy_name == "random":
            print("Policy: Random")
            policy = RandomPolicy(
                self.devices,
                self.app,
                self.emulator_path,
                self.android_system,
                self.root_path,
                self.pro_click,
                self.pro_longclick,
                self.pro_scroll,
                self.pro_edit,
                self.pro_naturalscreen,
                self.pro_leftscreen,
                self.pro_back,
                self.pro_splitscreen,
                self.pro_home,
            )
        else:
            print("No valid input policy specified. Using policy \"none\".")
            policy = None
        return policy

    def execute_event(self, device, event, num):
        print(f"Executing event: {event.action}")
        print(f"Event view: {event.view}")
        
        # 检查 view 的属性
        # print(f"View line: {event.view.line}")
        # print(f"View bounds: {event.view.bounds}")
        try:
            have_view_action = ["click", "longclick", "edit", "scroll"]
            feature = ""
            if event.action in have_view_action and event.view is not None:
                if (
                    device.use(resourceId=event.view.resourceId).count == 0
                    or device.use(className=event.view.className).count == 0
                ):
                    lines = device.use.dump_hierarchy()
                    if (
                        event.view.resourceId != ""
                        and event.view.resourceId not in lines
                    ) or (
                        event.view.className != "" and event.view.className not in lines
                    ):
                        return False

            if event.action.startswith("setting_"):
                self.injector.replay_setting(event, self.strategy_list)
            elif event.action == "check_setting_request":
                self.checker.check_setting_request()
            elif event.action == "click":
                feature = device.click(event.view, self.strategy_list)
            elif event.action == "longclick":
                device.longclick(event.view, self.strategy_list)
            elif event.action == "edit":
                device.edit(event.view, self.strategy_list, event.text)
            elif event.action == "scroll":
                device.scroll(event.view, self.strategy_list)
            elif event.action == "back":
                device.use.press("back")
            elif event.action == "home":
                device.use.press("home")
            elif event.action == "naturalscreen":
                device.use.set_orientation("n")
            elif event.action == "leftscreen":
                device.use.set_orientation("l")
            elif event.action == "start":
                device.start_app(self.app)
            elif event.action == "stop":
                device.stop_app(self.app)
            elif event.action == "clear":
                device.clear_app(self.app, self.is_login_app)
            elif event.action == "restart":
                device.restart(self.emulator_path, self.emulator_name)
            else:
                self.injector.replay_setting(event, self.strategy_list)

            print(device.device_serial + ":" + feature + ":end execute\n")
            time.sleep(self.rest_interval * 1)

            # 处理连续的权限弹窗
            permission_texts = ["OK", "ALLOW", "允许", "确定", "继续", "GRANT", "Get Started"]
            
            # 多次尝试处理权限，直到没有更多权限弹窗
            max_attempts = 5  # 防止无限循环
            current_attempt = 0
            
            while current_attempt < max_attempts:
                # 标记是否处理了任何权限
                handled_permission = False
                
                for text in permission_texts:
                    if device.use(text=text).exists():
                        print(f"Clicking permission2: {text}")
                        device.use(text=text).click()
                        time.sleep(1)  # 等待权限处理
                        handled_permission = True
                        break  # 处理一个权限后重新检查
                
                # 如果没有处理任何权限，退出循环
                if not handled_permission:
                    break
                
                current_attempt += 1
            
            
            return True
        except Exception as ex:
            if num == 0:
                print(ex)
                return self.execute_event(device, event, 1)
            else:
                print(ex)
                return False

    def replay(self, strategy):
        # init
        self.injector.init_setting()
        action_list = ["click", "long_click", "edit"]
        self.devices[1].set_strategy(strategy)
        path = os.path.join(self.root_path, f"strategy_{strategy}")
        self.error_path = os.path.join(path, "error_replay")
        self.utils.create_dir(self.error_path)
        self.f_replay_record = open(
            os.path.join(path, "error_replay.txt"), 'w', encoding='utf-8'
        )
        self.error_event_lists = []
        if not os.path.exists(os.path.join(path, "error_realtime.txt")):
            print("You should run first before replaying!")
            return
        self.f_replay = open(
            os.path.join(path, "error_realtime.txt"), 'r', encoding='utf-8'
        )
        lines = self.f_replay.readlines()

        for line in lines:
            self.error_event_lists.append(line)
            if "Start::" in line:
                # init dir for each error
                print("Start")
                record_flag = False
                linelist = line.split("::")
                self.utils.create_dir(os.path.join(self.error_path, linelist[1]))
                self.screen_path = os.path.join(self.error_path, linelist[1], "screen/")
                self.utils.create_dir(self.screen_path)
                f_read_trace = open(
                    os.path.join(self.error_path, linelist[1], "read_trace.txt"),
                    'w',
                    encoding='utf-8',
                )
                print(self.screen_path)
            elif "End::" in line:
                # end
                if record_flag is True:
                    for theline in self.error_event_lists:
                        self.f_replay_record.write(theline)
                        self.f_replay_record.flush()
                    self.error_event_lists = []
                    record_flag = False
                    f_read_trace.close()
                    self.utils.generate_html(
                        os.path.join(self.error_path, linelist[1]),
                        os.path.join(self.error_path, linelist[1]),
                        linelist[1],
                    )
            elif line.strip() != "":
                print("-----------------------" + '\n' + line)
                f_read_trace.write(line)
                f_read_trace.flush()
                # replay each event
                crash_info = self.checker.check_crash()
                if crash_info is not None:
                    self.f_replay_record.write(crash_info)
                    self.f_replay_record.flush()
                elementlist = line.split("::")
                if len(elementlist) < 5:
                    continue
                event = self.get_replay_event(elementlist, line)
                event.print_event()
                if elementlist[1] == "save_state":
                    self.save_state(
                        event.device.device_num,
                        self.screen_path,
                        elementlist[0],
                        self.f_replay_record,
                    )
                else:
                    if event.action in action_list:
                        self.utils.draw_event(event)
                    args = (event.device, event, 0)
                    self.devices[event.device.device_num].set_thread(
                        self.execute_event, args
                    )
                    if event.device.device_num == 1:
                        self.utils.start_thread()
                        for device in self.devices:
                            if device.thread is not None:
                                success_flag = device.thread.get_result()
                                if not success_flag and not self.checkduplicate():
                                    print("write error")
                                    record_flag = True
                                    self.utils.draw_event(event)
                                    self.utils.draw_error_frame()
                                device.set_thread(None, None)
                    time.sleep(self.rest_interval * 1)
                if (
                    "device1" in line
                    and "save_state" in line
                    and self.devices[0].state is not None
                    and self.devices[1].state is not None
                    and not self.devices[0].state.same(self.devices[1].state)
                ):
                    print("different!")
                    event = Event(None, "wrong", self.devices[1], elementlist[0])
                    self.utils.draw_event(event)
                if "::start::" in line:
                    self.checker.check_start(0, strategy)

    def get_replay_event(self, elementlist, line):
        view = None
        if elementlist[4].strip() != "None":
            view = View(elementlist[4], None, [])
        if elementlist[2] == "device0":
            event = Event(view, elementlist[1], self.devices[0], elementlist[0])
        elif elementlist[2] == "device1":
            event = Event(view, elementlist[1], self.devices[1], elementlist[0])
        else:
            print(f"{line} error")
        return event

    def start_app(self, event_count):
        for device in self.devices:
            args = (self.app,)
            device.set_thread(device.start_app, args)
        self.utils.start_thread()

        for device in self.guest_devices:
            self.utils.write_read_event(
                "::start::all devices::None::None" + '\n',
                event_count,
                None,
                "all devices",
                device.device_num,
            )
            event = Event(None, "start", device, event_count)
            self.utils.write_event(event, device.device_num, device.f_trace)
            self.utils.draw_event(event)

    def clear_app(self, event_count):
        for device in self.devices:
            device.clear_app(self.app, self.is_login_app)
            device.use.set_orientation("n")

        for device in self.guest_devices:
            device.error_event_lists.clear()
            device.wrong_event_lists.clear()
            device.wrong_flag = True
            self.utils.write_read_event(
                "::clear::all devices::None::None" + '\n',
                event_count,
                None,
                "all devices",
                device.device_num,
            )
            event = Event(None, "clear", device, event_count)
            self.utils.write_event(event, device.device_num, device.f_trace)
            self.utils.draw_event(event)

    def clear_and_restart_app(self, event_count, strategy):
        # print("clear_and_restart_app 1 ")
        start_time = time.time()
        for device in self.devices:
            device.clear_app(self.app, self.is_login_app)
            device.use.set_orientation("n")
        for device in self.guest_devices:
            device.error_event_lists.clear()
            device.wrong_event_lists.clear()
            device.wrong_flag = True
            event = Event(None, "naturalscreen", device, event_count)
            self.utils.write_event(event, device.device_num, device.f_trace)
            event = Event(None, "clear", device, event_count)
            # event_count = self.write_draw_and_save_all(device, event, event_count)

        # if event_count>3:
        #     event=self.injector.change_setting_after_run(event_count,strategy)
        #     if event is not None:
        #         event_count = self.write_draw_and_save_one(event,event_count)

        # check keyboard
        self.checker.check_keyboard()

        for device in self.devices:
            args = (self.app,)
            device.set_thread(device.start_app, args)

        self.utils.start_thread()
        self.checker.check_start(0, strategy)
        

        for device in self.devices:
            event = Event(None, "start", device, event_count)
            event_count = self.write_draw_and_save_all(device, event, event_count)

        # event = self.injector.change_setting_before_run(event_count, strategy)

        # if event is not None:
        #     event_count = self.write_draw_and_save_one(event, event_count)
        end_time = time.time()
        # print(f"clear_and_restart_app time: {end_time - start_time} seconds")
        return event_count + 1

    def back_to_app(self, event_count, strategy):
        for device in self.devices:
            device.use.press("back")
        print("Back")
        time.sleep(self.rest_interval * 1)
        if not self.checker.check_foreground():
            for device in self.devices:
                device.stop_app(self.app)
                args = (self.app,)
                device.set_thread(device.start_app, args)
            self.utils.start_thread()
            self.checker.check_start(1, strategy)

            for device in self.guest_devices:
                self.utils.write_read_event(
                    "::restart::all devices::None::None" + '\n',
                    event_count,
                    None,
                    "all devices",
                    device.device_num,
                )
                event = Event(None, "back", device, event_count)
                self.utils.write_event(event, device.device_num, device.f_trace)
                event = Event(None, "home", device, event_count)
                self.utils.write_event(event, device.device_num, device.f_trace)
                event = Event(None, "start", device, event_count)
                self.utils.write_event(event, device.device_num, device.f_trace)
                self.utils.draw_event(event)
        else:
            for device in self.guest_devices:
                self.utils.write_read_event(
                    "::back::all devices::None::None" + '\n',
                    event_count,
                    None,
                    "all devices",
                    device.device_num,
                )
                event = Event(None, "back", device, event_count)
                self.utils.write_event(event, device.device_num, device.f_trace)
                self.utils.draw_event(event)

    def save_all_state(self, event_count):
        # start_time = time.time()
        # time.sleep(self.rest_interval * 1)
        # self.save_state(0, f"{self.devices[0].path}screen/", event_count, self.devices[0].f_trace)
        # for device in self.guest_devices:
        #     self.save_state(
        #         device.device_num, device.path + "screen/", event_count, device.f_trace
        #     )
        #     event = Event(None, "save_state", device, event_count)
        #     event.set_count(device.device_num)
        #     self.utils.write_event(event, device.device_num, device.f_trace)
        # end_time = time.time()
        # print(f"save_all_state time: {end_time - start_time} seconds")
        # return event_count + 1
        start_time = time.time()
        time.sleep(self.rest_interval * 1)
        
        # 先保存基准设备状态（不需要并行）
        self.save_state(0, f"{self.devices[0].path}screen/", event_count, self.devices[0].f_trace)
        
        # 并行处理 guest devices
        with ThreadPoolExecutor(max_workers=len(self.guest_devices)) as executor:
            def save_device_state(device):
                self.save_state(
                    device.device_num, device.path + "screen/", event_count, device.f_trace
                )
                event = Event(None, "save_state", device, event_count)
                event.set_count(device.device_num)
                self.utils.write_event(event, device.device_num, device.f_trace)
            
            # 并行执行 guest devices 的状态保存
            list(executor.map(save_device_state, self.guest_devices))
        
        end_time = time.time()
        # print(f"save_all_state time: {end_time - start_time} seconds")
        return event_count + 1

        
        

    def update_all_state(self, event_count):
        # time.sleep(self.rest_interval * 1)
        # event_count = event_count - 1
        # self.update_state(0, f"{self.devices[0].path}screen/", event_count, self.devices[0].f_trace)
        # for device in self.guest_devices:
        #     self.update_state(
        #         device.device_num,
        #         f"{device.path}screen/",
        #         event_count,
        #         device.f_trace,
        #     )
        # event_count = event_count + 1
        # 使用线程池并行更新设备状态
        start_time = time.time()

        event_count = event_count - 1
    
        with ThreadPoolExecutor(max_workers=len(self.devices)) as executor:
            futures = {}
            for device_idx, device in enumerate(self.devices):
                try:
                    # 重新构造原始方法的完整参数
                    path = f"{device.path}screen/"
                    
                    # 获取设备层级信息
                    lines = device.use.dump_hierarchy().splitlines()
                    
                    # 创建 State 对象
                    state = State(lines)
                    
                    # 提交更新任务，保留原始方法的所有参数
                    futures[executor.submit(
                        self.update_state, 
                        device_idx,  # device_count
                        path,        # path
                        event_count, # event_count
                        device.f_trace  # f_trace
                    )] = device
                except Exception as e:
                    print(f"Error preparing state for device {device.device_serial}: {e}")
            
            # 等待并处理结果
            for future in as_completed(futures):
                device = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Error updating state for device {device.device_serial}: {e}")
        
        end_time = time.time()
        # print(f"update_all_state time: {end_time - start_time} seconds")
        event_count = event_count + 1

    def save_state(self, device_count, path, event_count, f_trace):
        # get and save state of all devices
        lines = self.devices[device_count].screenshot_and_getstate(path, event_count)
        state = State(lines)
        self.devices[device_count].update_state(state)

    def update_state(self, device_count, path, event_count, f_trace):
        lines = self.devices[device_count].use.dump_hierarchy().splitlines()
        state = State(lines)
        self.devices[device_count].update_state(state)
        if self.devices[device_count].last_state != self.devices[device_count].state:
            self.save_state(device_count, path, event_count, f_trace)

    def restart_devices(self, event_count):
        # print("restart_devices")
        start_time = time.time()
        for device in self.devices:
            if device.is_emulator == 0:
                device.restart(self.emulator_path, self.emulator_name)
        end_time = time.time()
        print(f"restart_devices time: {end_time - start_time} seconds")
        # for device in self.guest_devices:
        #     device.connect()
        #     device.error_event_lists.clear()
        #     device.wrong_event_lists.clear()
        #     device.wrong_flag=True
        #     self.utils.write_read_event("::restart::all devices::None::None"+'\n',event_count,None,"all devices",device.device_num)
        #     event = Event(None, "restart", device, event_count)
        #     self.utils.write_event(event,device.device_num,device.f_trace)
        #     self.utils.draw_event(event)

    def wait_load(self, event_count):
        start_time = time.time()
        try:
            wait_time = self.checker.check_loading()
            if wait_time > 0:
                event_count = event_count - 1
                event_count = self.save_all_state(event_count)
        except Exception:
            import traceback

            traceback.print_exc()
            self.restart_devices()
        end_time = time.time()
        # print(f"wait_load time: {end_time - start_time} seconds")

    def write_draw_and_save_one(self, event, event_count):
        start_time = time.time()
        self.utils.write_read_event(
            None, event_count, event, "all device", event.device.device_num
        )
        self.utils.write_one_device_event(
            event, event.device.device_num, event.device.f_trace
        )
        self.utils.draw_event(event)
        event_count = self.save_all_state(event_count)
        end_time = time.time()
        # print(f"write_draw_and_save_one time: {end_time - start_time} seconds")
        return event_count

    def write_draw_and_save_all(self, device, event, event_count):
        start_time = time.time()
        self.utils.write_read_event(
            None, event_count, event, "all device", event.device.device_num
        )
        self.utils.write_event(event, device.device_num, device.f_trace)
        self.utils.draw_event(event)
        event_count = self.save_all_state(event_count)
        end_time = time.time()
        # print(f"write_draw_and_save_all time: {end_time - start_time} seconds")
        return event_count

    def read_event(self, line, event_count):
        eventlist = line.split("::")
        action = eventlist[1]
        if eventlist[4] != "None\n":
            view = View(eventlist[4], None, [])
            event = Event(view, action, self.devices[0], event_count)
        else:
            event = Event(None, action, self.devices[0], event_count)
        return event

    def test(self):
        for device in self.guest_devices:
            self.checker.check_language(self.root_path + "/strategy_language/")

    def checkduplicate(self):
        # 检查基准设备
        for screen in self.deduplicate_list1:
            if self.devices[0].state.same(screen):
                return True
                
        # 检查其他设备
        for i in range(1, len(self.devices)):
            device_idx = i - 1  # 转换为deduplicate_lists的索引
            for screen in self.deduplicate_lists[device_idx]:
                if self.devices[i].state.same(screen):
                    return True
                    
        # 保存当前状态
        self.deduplicate_list1.append(self.devices[0].state)
        for i in range(1, len(self.devices)):
            device_idx = i - 1  # 转换为deduplicate_lists的索引
            self.deduplicate_lists[device_idx].append(self.devices[i].state)
        return False

    def restart_devices_and_install_app_and_data(self):
        # connect device and install app
        if self.is_login_app != 0: #默认是1 非登录应用模式
            # self.restart_devices(0)
            print("restart_devices and install app and data 1 ")
            start_time = time.time()
            # 使用 bash 脚本批量重启模拟器
            try:
                subprocess.run(
                    ["./start_emulator.sh", str(len(self.devices))], 
                    check=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
                print(f"Successfully restarted {len(self.devices)} emulators")
            except subprocess.CalledProcessError as e:
                print(f"Error restarting emulators: {e}")
                print(f"Standard output: {e.stdout.decode('utf-8')}")
                print(f"Standard error: {e.stderr.decode('utf-8')}")
                return

            # self.parallel_device_connect()


            for i, device in enumerate(self.devices):
                device.connect()
                if i < len(self.app_path):
                    device.install_app(self.app_path[i], self.app)
                    print(f"Installed app {self.app_path[i]} on device {device.device_serial}")
                else:
                    # 如果设备数量超过应用数量，使用最后一个应用
                    device.install_app(self.app_path[-1], self.app)
                    print(f"Installed app {self.app_path[-1]} on device {device.device_serial} (fallback)")

            end_time = time.time()
            print(f"restart_devices_and_install_app_and_data time: {end_time - start_time} seconds")
        
        else:
            # for device in self.devices:
            #     device.restart(self.emulator_path, self.emulator_name)
            #     device.connect()
            #     print(f"Restarted and connected device {device.device_serial}")
            # 使用 bash 脚本批量重启模拟器
            try:
                subprocess.run(
                    ["./start_emulator.sh", str(len(self.devices))], 
                    check=True, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE
                )
                print(f"Successfully restarted {len(self.devices)} emulators")
            except subprocess.CalledProcessError as e:
                print(f"Error restarting emulators: {e}")
                print(f"Standard output: {e.stdout.decode('utf-8')}")
                print(f"Standard error: {e.stderr.decode('utf-8')}")
                return

            for device in self.devices:
                device.connect()
            # self.parallel_device_connect()

        # # add some files to all devices
        resourcelist = os.listdir(self.resource_path)
        for device in self.devices:
            device.disable_keyboard()
            device.log_crash(f"{self.root_path}/{device.device_serial}_logcat.txt")
            # for resource in resourcelist:
            #     device.add_file(self.resource_path, resource, "/sdcard")
            print(f"Added resources to device {device.device_serial}")
            # if "anki" in self.app.package_name:
            #     device.mkdir("/storage/emulated/0/AnkiDroid/")
            #     print("add collection.anki2 for"+str(device.device_serial))
            #     device.add_file(self.resource_path,"collection.anki2","/storage/emulated/0/AnkiDroid/")

    
    
    def start(self, strategy):
        # if execute serial, init the strategy of device1, otherwise, init all the guest devices' strategies
        if self.serial_or_parallel == 0:
            self.devices[0].use.press("home")
            self.devices[0].set_strategy(strategy)

            for device in self.guest_devices:
                device.use.press("home")
                device.set_strategy(strategy)  # 使用相同的策略
                device.make_strategy(self.root_path)

        else:
            for device in self.guest_devices:
                device.set_strategy(self.strategy_list[device.device_num - 1])
                device.make_strategy(self.root_path)

        run_count = self.start_testcase_count
        print("Executor start 1 ")

       
        
        while run_count < self.testcase_count:
            start_time = time.time()
            print(f"Starting test case {run_count}")
            if run_count > 0:
                print("Executor start 2 ")
                self.restart_devices_and_install_app_and_data()
            # create folder of new run
            run_count = run_count + 1

            # 初始化基准设备
            self.devices[0].make_strategy_runcount(run_count, self.root_path)
        
            
            # 初始化其他设备
            for device in self.guest_devices:
                device.use.press("back")
                device.use.press("back")
                device.make_strategy_runcount(run_count, self.root_path)
            
            
            # init setting
            event_count = 1.0
            now_start_time = time.time()
            event_count = self.save_all_state(event_count) # event count + 1
            end_time = time.time()
            # print(f"1.init setting time: {end_time - now_start_time} seconds")
            
            # self.injector.init_setting()

            # clear and start app
            now_start_time = time.time()
            event_count = self.clear_and_restart_app(event_count, strategy)
            end_time = time.time()
            # print(f"2.clear_and_restart_app time: {end_time - now_start_time} seconds")

            for device in self.devices:
                print(f"debug skip_welcome1: {self.app.package_name}")
                device.skip_welcome(self.app.package_name)

            # 处理连续的权限弹窗
            permission_texts = ["OK", "ALLOW", "允许", "确定", "继续",  "GRANT", "Get Started"]

            for device in self.devices:
                # 多次尝试处理权限，直到没有更多权限弹窗
                max_attempts = 5  # 防止无限循环
                current_attempt = 0
                
                while current_attempt < max_attempts:
                    # 标记是否处理了任何权限
                    handled_permission = False
                    
                    for text in permission_texts:
                        if device.use(text=text).exists():
                            print(f"Clicking permission1: {text}")
                            device.use(text=text).click()
                            time.sleep(1)  # 等待权限处理
                            handled_permission = True
                            break  # 处理一个权限后重新检查
                    
                    # 如果没有处理任何权限，退出循环
                    if not handled_permission:
                        break
                    
                    current_attempt += 1

            while event_count < self.event_num:
                # 更新所有设备状态
                now_start_time = time.time()
                self.update_all_state(event_count)
                end_time = time.time()
                # print(f"3.update_all_state time: {end_time - now_start_time} seconds")
                
                # 只检查非失败设备的状态
                now_start_time = time.time()
                active_devices = [device for device in self.devices if not (hasattr(device, 'has_failed') and device.has_failed)]
                change_flag = any(device.last_state != device.state for device in active_devices)
                end_time = time.time()
                # print(f"4.check_state time: {end_time - now_start_time} seconds")

                now_start_time = time.time()
                if self.devices[0].last_state is not None and change_flag:
                    # 等待加载
                    self.wait_load(event_count)

                    # 检查应用是否在前台
                    if not self.checker.check_foreground():
                        print("Not foreground")
                        self.back_to_app(event_count, strategy)
                        self.checker.check_loading()
                        event_count = self.save_all_state(event_count)

                    self.checker.check_crash()
                    self.checker.check_keyboard()
                end_time = time.time()
                # print(f"5.check_crash and check_keyboard time: {end_time - now_start_time} seconds")

                # 检查每个非基准设备的状态和执行结果
                newly_failed = []  # 本次新失败的设备
                all_failed = True  # 是否所有未失败的设备都失败了
                
                # 检查每个非基准设备的状态
                now_start_time = time.time()
                for i in range(1, len(self.devices)):
                    # 跳过已经失败的设备
                    if hasattr(self.devices[i], 'has_failed') and self.devices[i].has_failed:
                        continue
                    
                    # 检查设备状态是否一致
                    if not self.devices[0].state.same(self.devices[i].state):
                        print(f"Device {i} state is different!")
                        self.utils.write_error(
                            i,  # 使用实际的设备编号
                            run_count,
                            self.devices[i].wrong_event_lists,
                            self.devices[i].f_wrong,
                            self.devices[i].wrong_num
                        )
                        self.devices[i].wrong_num += 1
                        
                        # 记录错误事件
                        event = Event(None, "wrong", self.devices[i], event_count)
                        self.utils.draw_event(event)
                    
                

                
                end_time = time.time()
                # print(f"6.check_state time: {end_time - now_start_time} seconds")

                now_start_time = time.time()
                
                # 选择事件（始终从基准设备选择）
                event = self.policy.choose_event(self.devices[0], event_count)
                
                # 更新上一个事件
                self.last_event = event
                
                end_time = time.time()
                # print(f"8.choose_event time: {end_time - now_start_time} seconds")

                now_start_time = time.time()
                self.utils.draw_event(event)
                event.print_event()
                end_time = time.time()
                # print(f"9.draw_event time: {end_time - now_start_time} seconds")

                # 执行事件
                now_start_time = time.time()
                for device in self.devices:
                    # 跳过已经失败的设备
                    if hasattr(device, 'has_failed') and device.has_failed:
                        continue

                    # 删除已存在的线程属性
                    if hasattr(device, 'thread'):
                        delattr(device, 'thread')
                    
                    args = (device, event, 0)
                    device.set_thread(self.execute_event, args)
                
                # 启动线程执行事件
                self.utils.start_thread()
                end_time = time.time()
                # print(f"10.start_thread time: {end_time - now_start_time} seconds")
                
                # 检查基准设备执行结果
                now_start_time = time.time()
                base_success = self.devices[0].thread.get_result()
                if not base_success:
                    # 基准设备失败，直接跳过当前事件
                    print(f"Base device failed at event {event_count}, action: {event.action}")
                    
                    # # 如果是权限相关的失败，添加额外的日志
                    # if event.view and "permission" in str(event.view.resourceId).lower():
                    #     print(f"WARNING: Permission dialog encountered at event {event_count}")
                    #     print(f"Permission details: {event.view.text}, Resource ID: {event.view.resourceId}")
                    
                    self.utils.print_dividing_line(False, event_count)
                    # 递增 event_count，避免卡在同一个事件
                    event_count += 1
                    continue
                
                end_time = time.time()
                # print(f"11.check base device time: {end_time - now_start_time} seconds")

                now_start_time = time.time()
                # 检查其他设备的执行结果
                for i in range(1, len(self.devices)):
                    # 跳过已经失败的设备
                    if hasattr(self.devices[i], 'has_failed') and self.devices[i].has_failed:
                        continue
                    
                    device_success = self.devices[i].thread.get_result()
                    if device_success:
                        # 至少有一个设备还在运行
                        all_failed = False
                    else:
                        # 设备执行失败
                        newly_failed.append(i)
                        self.devices[i].has_failed = True
                        print(f"Device {i} failed, recording error and skipping its future events")
                        
                        # 记录错误事件
                        self.utils.print_dividing_line(False, event_count, i)
                        self.utils.write_event(
                            event, i, self.devices[i].f_trace
                        )
                        self.utils.draw_event(event)
                        
                        # 保存失败设备的截图和布局信息
                        try:
                            # 将 run_count 转换为字符串
                            run_count_str = str(int(run_count)) if isinstance(run_count, float) else str(run_count)
                            
                            # 确保 root_path 和 screen_error 目录存在
                            screen_error_path = os.path.join(self.root_path, run_count_str, "screen_error/")
                            os.makedirs(screen_error_path, exist_ok=True)
                            
                            # 保存截图和布局
                            screenshot_path = os.path.join(screen_error_path, f"{event_count}_device_{device.device_num}.png")
                            xml_path = os.path.join(screen_error_path, f"{event_count}_device_{device.device_num}.xml")
                            
                            # 使用 screenshot_and_getstate 方法同时保存截图和布局
                            device.screenshot_and_getstate(screen_error_path, event_count)
                            
                            # 记录当前事件信息
                            event_info_path = os.path.join(self.root_path, run_count_str, "event_info_error")
                            os.makedirs(event_info_path, exist_ok=True)
                            
                            with open(os.path.join(event_info_path, f"event_info_error_{event_count}_device_{device.device_num}.txt"), "w") as f:
                                f.write(f"Run Count: {run_count}\n")
                                f.write(f"Event Count: {event_count}\n")
                                
                                # 记录事件详细信息
                                f.write(f"Action: {event.action}\n")
                                
                                # 记录视图信息（如果存在）
                                if event.view is not None:
                                    f.write("View Details:\n")
                                    f.write(f"  Text: {event.view.text}\n")
                                    f.write(f"  Description: {event.view.description}\n")
                                    f.write(f"  Resource ID: {event.view.resourceId}\n")
                                    f.write(f"  Package: {event.view.package}\n")
                                    f.write(f"  Class Name: {event.view.className}\n")
                                    f.write(f"  X: {event.view.x}, Y: {event.view.y}\n")
                                    f.write(f"  Line: {event.view.line}\n")
                                
                                # 记录设备信息
                                f.write("Device Details:\n")
                                f.write(f"  Device Number: {device.device_num}\n")
                                f.write(f"  Device Serial: {device.device_serial}\n")
                                
                                f.write(f"Base Device Success: {base_success}\n")
                                
                                # 记录基准设备的事件详细信息
                                base_device = self.devices[0]
                                f.write("\nBase Device Event Details:\n")
                                f.write(f"  Base Device Number: {base_device.device_num}\n")
                                f.write(f"  Base Device Serial: {base_device.device_serial}\n")
                                
                                # 记录基准设备当前事件的详细信息
                                f.write("  Current Event Details:\n")
                                f.write(f"    Action: {event.action}\n")
                                
                                # 记录基准设备当前事件的视图信息（如果存在）
                                if event.view is not None:
                                    f.write("    View Details:\n")
                                    f.write(f"      Text: {event.view.text}\n")
                                    f.write(f"      Description: {event.view.description}\n")
                                    f.write(f"      Resource ID: {event.view.resourceId}\n")
                                    f.write(f"      Package: {event.view.package}\n")
                                    f.write(f"      Class Name: {event.view.className}\n")
                                    f.write(f"      X: {event.view.x}, Y: {event.view.y}\n")
                                    f.write(f"      Line: {event.view.line}\n")
                                
                                # 记录基准设备上一个事件的详细信息
                                if self.last_event is not None:
                                    f.write("  Last Event Details:\n")
                                    f.write(f"    Last Action: {self.last_event.action}\n")
                                    
                                    if self.last_event.view is not None:
                                        f.write("    Last View Details:\n")
                                        f.write(f"      Last Text: {self.last_event.view.text}\n")
                                        f.write(f"      Last Description: {self.last_event.view.description}\n")
                                        f.write(f"      Last Resource ID: {self.last_event.view.resourceId}\n")
                                        f.write(f"      Last Package: {self.last_event.view.package}\n")
                                        f.write(f"      Last Class Name: {self.last_event.view.className}\n")
                                        f.write(f"      Last X: {self.last_event.view.x}, Y: {self.last_event.view.y}\n")
                                        f.write(f"      Last Line: {self.last_event.view.line}\n")
                                
                                # 保存上一个事件的截图和布局
                                if self.last_event is not None:
                                    try:
                                        # 保存上一个事件的截图和布局
                                        last_screenshot_path = os.path.join(screen_error_path, f"last_{event_count}_device_{device.device_num}.png")
                                        device.screenshot_and_getstate(screen_error_path, event_count)
                                        
                                        # 保存上一个事件的基准设备截图和布局
                                        base_device = self.devices[0]
                                        last_base_screenshot_path = os.path.join(screen_error_path, f"last_base_{event_count}_device_{base_device.device_num}.png")
                                        base_device.screenshot_and_getstate(screen_error_path, event_count)
                                    except Exception as e:
                                        print(f"Error saving last event info for device {device.device_num}: {e}")
                                        
                                        # 保存当前事件的基准设备截图和布局
                                        base_device = self.devices[0]
                                        base_screenshot_path = os.path.join(screen_error_path, f"base_{event_count}_device_{base_device.device_num}.png")
                                        base_device.screenshot_and_getstate(screen_error_path, event_count)
                        except Exception as e:
                            print(f"Error saving device {device.device_num} info: {e}")
                        
                        # 记录错误事件
                        self.utils.print_dividing_line(False, event_count, i)
                        self.utils.write_event(
                            event, i, self.devices[i].f_trace
                        )
                        self.utils.draw_event(event)
                        
                        # 检查是否重复
                        if not self.checkduplicate():
                            print("write error")
                            self.utils.draw_error_frame()
                            self.utils.write_error(
                                i,
                                run_count,
                                self.devices[i].error_event_lists,
                                self.devices[i].f_error,
                                self.devices[i].error_num
                            )
                            self.devices[i].error_num += 1
                            
                            # 保存状态并重启应用
                            event_count = self.save_all_state(event_count)
                            event_count = self.clear_and_restart_app(event_count, strategy)
                            break  # 跳出循环，重新开始事件选择
                
                end_time = time.time()
                # print(f"12.check other devices time: {end_time - now_start_time} seconds")

                now_start_time = time.time()
                # 如果所有未失败的设备都失败了，重启所有设备
                if all_failed and newly_failed:
                    print("All remaining devices have failed, restarting all devices")
                    # 重置所有设备的失败状态
                    for device in self.devices[1:]:
                        if hasattr(device, 'has_failed'):
                            delattr(device, 'has_failed')
                    
                    # 保存状态并重启所有设备
                    event_count = self.save_all_state(event_count)
                    event_count = self.clear_and_restart_app(event_count, strategy)
                    continue
                
                end_time = time.time()
                # print(f"13.check all failed time: {end_time - now_start_time} seconds")

                
                # 记录执行结果
                now_start_time = time.time()
                self.utils.print_dividing_line(True, event_count, self.devices[0].device_num)
                end_time = time.time()
                # print(f"14.print_dividing_line time: {end_time - now_start_time} seconds")
                
                # 记录基准设备的执行结果
                now_start_time = time.time()
                self.utils.write_read_event(
                    None, event_count, event, "all device", self.devices[0].device_num
                ) # 只记录base设备的事件
                self.utils.write_event(event, self.devices[0].device_num, self.devices[0].f_trace)
                
                end_time = time.time()
                # print(f"15.write_read_event time: {end_time - now_start_time} seconds")

                now_start_time = time.time()
                # 记录其他设备的执行结果（只记录未失败的设备）
                for i in range(1, len(self.devices)):
                    if not (hasattr(self.devices[i], 'has_failed') and self.devices[i].has_failed):
                        self.utils.write_event(event, i, self.devices[i].f_trace)
                
                end_time = time.time()
                # print(f"16.write_event time: {end_time - now_start_time} seconds")

                now_start_time = time.time()
                # 保存所有设备的状态
                event_count = self.save_all_state(event_count)
                end_time = time.time()
                # print(f"17.save_all_state time: {end_time - now_start_time} seconds")

                end_time = time.time()
                print(f"one run time: {end_time - start_time} seconds")

                # injecte a setting change
                # event=self.injector.inject_setting_during_run(event_count,strategy,request_flag)
                # if event is not None:
                #     event_count = self.write_draw_and_save_one(event,event_count)

            # event=self.injector.change_setting_after_run(event_count,strategy)
            # if event is not None:
            #     event_count = self.write_draw_and_save_one(event,event_count)

        
            # at the end of each run, generate a html file
            for device in self.guest_devices:
                self.utils.generate_html(device.path, device.path, run_count)
            
        
