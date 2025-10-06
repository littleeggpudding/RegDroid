
import os
import re
import traceback

from event import Event


class Utils(object):

    def __init__(self, devices):
        self.devices = devices

    def write_error(self, fail_device, run_count, event_list, f_write, num):
        # print("write_error")
        event_count = 0
        f_write.write("Start::"+str(num+1)+"::run_count::"+str(run_count)+'\n')
        for event in event_list:
            event_count = event_count+1
            if event.view is not None:
                f_write.write(str(event.event_count)+"::"+event.action+"::device" +
                              str(event.device.device_num)+"::"+event.text+"::"+event.view.line)
            else:
                f_write.write(str(event.event_count)+"::"+event.action+"::device" +
                              str(event.device.device_num)+"::"+event.text+"::None::"+'\n')
            f_write.flush
        f_write.write("End::"+'\n'+'\n')
        f_write.flush()

    def write_read_event(self, string, event_count, event, device_string, device_count):
        # f_read_trace = self.devices[device_count].f_read_trace
        # if string is not None:
        #     f_read_trace.write(str(event_count)+string)
        # else:
        #     if event.view is not None:
        #         f_read_trace.write(str(event_count)+"::"+event.action+"::"+device_string +
        #                            "::"+event.text+"::"+event.view.text+"::"+event.view.description+'\n')
        #     else:
        #         f_read_trace.write(str(event_count)+"::"+event.action +
        #                            "::"+device_string+"::"+event.text+"::None::None"+'\n')
        # f_read_trace.flush()
        
        f_read_trace = self.devices[device_count].f_read_trace
        if string is not None:
            f_read_trace.write(str(event_count)+string)
        else:
            if event.view is not None:
                f_read_trace.write(
                    str(event_count)+"::"+
                    event.action+"::"+
                    device_string+"::"+
                    event.text+"::"+
                    event.view.text+"::"+
                    event.view.description+"::"+
                    event.view.resourceId+"::"+
                    event.view.className+"::"+
                    event.view.bounds+'\n'
                )
            else:
                f_read_trace.write(
                    str(event_count)+"::"+
                    event.action+"::"+
                    device_string+"::"+
                    event.text+"::None::None::None::None::None::None"+'\n'
                )
        f_read_trace.flush()

    def write_one_device_event(self, event, device_count, f_trace):
        if event.view is not None:
            f_trace.write(str(event.event_count)+"::"+event.action+"::device"+str(
                self.devices[device_count].device_num)+"::"+event.text+"::"+event.view.line)
        else:
            f_trace.write(str(event.event_count)+"::"+event.action+"::device" +
                          str(self.devices[device_count].device_num)+"::"+event.text+"::None"+'\n')
        f_trace.flush()
        event.set_device(self.devices[device_count])
        self.devices[device_count].error_event_lists.append(event)
        self.devices[device_count].wrong_event_lists.append(event)

    def write_event(self, event, device_count, f_trace):
        if event.view is not None:
            f_trace.write(str(event.event_count)+"::"+event.action+"::device"+str(
                self.devices[device_count].device_num)+"::"+event.text+"::"+event.view.line)
            # f_trace.write(str(event.event_count)+"::"+event.action+"::device" +
            #               str(self.devices[0].device_num)+"::"+event.text+"::"+event.view.line)
        else:
            f_trace.write(str(event.event_count)+"::"+event.action+"::device" +
                          str(self.devices[device_count].device_num)+"::"+event.text+"::None"+'\n')
            # f_trace.write(str(event.event_count)+"::"+event.action+"::device" +
            #               str(self.devices[0].device_num)+"::"+event.text+"::None"+'\n')
        f_trace.flush()
        event.set_device(self.devices[0])
        self.devices[device_count].error_event_lists.append(event)
        self.devices[device_count].wrong_event_lists.append(event)
        new_event = Event(event.view, event.action,
                          self.devices[device_count], event.event_count)
        self.devices[device_count].error_event_lists.append(new_event)
        self.devices[device_count].wrong_event_lists.append(new_event)

    def start_thread(self):
        # 只启动未启动的线程
        for device in self.devices:
            if hasattr(device, 'thread') and device.thread is not None:
                # 检查线程是否已经启动
                if not hasattr(device.thread, '_started') or not device.thread._started.is_set():
                    device.thread.start()
        
        # 等待所有线程完成
        for device in self.devices:
            if hasattr(device, 'thread') and device.thread is not None:
                device.thread.join()

    def create_dir(self, path):
        if not os.path.isdir(path):
            os.makedirs(path)

    def draw_error_frame(self):
        for device in self.devices:
            import cv2
            image = cv2.imread(device.screenshot_path)
            cv2.rectangle(image, (1, 1), (1430, 2550), (0, 0, 255), 20)
            cv2.imwrite(device.screenshot_path, image)

    # def draw_event(self, event):
    #     try:
    #         for device in self.devices:
    #             import cv2
    #             image = cv2.imread(device.screenshot_path)
    #             if device.screenshot_path is not None and event.view is not None:
    #                 if event.action == "click":
    #                     cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (0, 0, 255), 5)
    #                 elif event.action == "longclick":
    #                     cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (0, 225, 255), 5)
    #                 elif event.action == "edit":
    #                     cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (225, 0, 255), 5)
    #                 else:
    #                     cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (225, 225, 255), 5)
    #             else:
    #                 if event.action == "wrong":
    #                     cv2.rectangle(image, (0, 0), (1430, 2550), (0, 225, 255), 20)
    #                 else:
    #                     cv2.putText(image, event.action, (100, 300),
    #                                 cv2.FONT_HERSHEY_SIMPLEX, 5, (0, 0, 255), 1, cv2.LINE_AA)
    #             # image=cv2.resize(image, (256, 512))
    #             cv2.imwrite(device.screenshot_path, image)
    #     except Exception:
    #         traceback.print_exc()
    
    def draw_event(self, event):
        try:
            import cv2
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            def process_device_image(device):
                image = cv2.imread(device.screenshot_path)
                if device.screenshot_path is not None and event.view is not None:
                    if event.action == "click":
                        cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (0, 0, 255), 5)
                    elif event.action == "longclick":
                        cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (0, 225, 255), 5)
                    elif event.action == "edit":
                        cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (225, 0, 255), 5)
                    else:
                        cv2.rectangle(image, (int(event.view.xmin), int(event.view.ymin)), (int(event.view.xmax), int(event.view.ymax)), (225, 225, 255), 5)
                else:
                    if event.action == "wrong":
                        cv2.rectangle(image, (0, 0), (1430, 2550), (0, 225, 255), 20)
                    else:
                        cv2.putText(image, event.action, (100, 300),
                                    cv2.FONT_HERSHEY_SIMPLEX, 5, (0, 0, 255), 1, cv2.LINE_AA)
                cv2.imwrite(device.screenshot_path, image)
            
            with ThreadPoolExecutor(max_workers=len(self.devices)) as executor:
                futures = {executor.submit(process_device_image, device): device for device in self.devices}
                
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"Error processing device {futures[future].device_serial}: {e}")
        
        except Exception:
            traceback.print_exc()

    def find_trace_details(self, lines_trace, state_num):
        details = {
            'action': None,
            'event_text': None,
            'view_text': None,
            'view_description': None,
            'view_resourceId': None,
            'view_className': None
        }
        
        for line in lines_trace:
            line_num = line[0:line.find("::")]
            if self.is_number(line_num) and self.is_number(state_num):
                if float(state_num) + 1.0 == float(line_num):
                    # 分割行
                    parts = line.split("::")
                    
                    # 确保有足够的部分
                    if len(parts) >= 7:
                        details['action'] = parts[1]
                        details['event_text'] = parts[3]
                        details['view_text'] = parts[4]
                        details['view_description'] = parts[5]
                        details['view_resourceId'] = parts[6]
                        details['view_className'] = parts[7].strip()
                    
                    break
        
        return details

    def generate_html(self, path, html_path, run_count):
        line_list = []
        f_html = open(os.path.join(html_path, str(run_count) + "_trace.html"), 'w', encoding='utf-8')
        f_style = open("style.html", 'r', encoding='utf-8')
        f_write_trace = open(os.path.join(path, "read_trace.txt"), 'r', encoding='utf-8')
        lines_trace = f_write_trace.readlines()
        img_list = os.listdir(path+"/screen")
        
        # 添加自定义 CSS 来实现图片垂直排列
        custom_style = """
        <style>
        .device-images {
            display: flex;
            flex-direction: column;
            align-items: center;
            margin-bottom: 10px;
        }
        .device-images img {
            max-width: 100%;
            height: auto;
            margin: 5px 0;
        }
        </style>
        """
        
        new_str = "<ul id=\"menu\">"+'\n'

        # 按状态号分组图片
        state_images = {}
        for img_file in img_list:
            if ".png" in img_file:
                num = img_file.find("_")
                state_num = img_file[0:num]
                if state_num not in state_images:
                    state_images[state_num] = []
                state_images[state_num].append(img_file)

        # 按状态号排序处理
        for state_num in sorted(state_images.keys(), key=float):
            # 获取当前状态的所有设备截图
            device_imgs = state_images[state_num]
            
            # 生成 HTML 行
            line_content = "      <li>"
            line_content += "<div class=\"device-images\">"
            for img_file in device_imgs:
                if path == html_path:
                    line_content += f"<img src=\"screen/{img_file}\" class=\"img\">"
                else:
                    line_content += f"<img src=\"{run_count}/screen/{img_file}\" class=\"img\">"
            line_content += "</div>"
            
            # 尝试找到对应的动作描述
            # action = None
            # for line in lines_trace:
            #     line_num = line[0:line.find("::")]
            #     if self.is_number(line_num) and self.is_number(state_num):
            #         if float(state_num) + 1.0 == float(line_num):
            #             line = line[line.find("::") + 2 : len(line)]
            #             action = line[0:line.find("::")]
            #             break
            trace_details = self.find_trace_details(lines_trace, state_num)
            action = trace_details['action']
            event_text = trace_details['event_text']
            view_text = trace_details['view_text']
            view_description = trace_details['view_description']
            view_resourceId = trace_details['view_resourceId']
            view_className = trace_details['view_className']

            line_content += f"""
            <div class="event-container">
                <ul>
                    <li>State: {state_num}</li>
                    <li>Action: {action}</li>
                    <li>Event Text: {event_text}</li>
                    <li>View Text: {view_text}</li>
                    <li>Description: {view_description}</li>
                    <li>Resource ID: {view_resourceId}</li>
                    <li>Class Name: {view_className}</li>
                </ul>
            </div>
            """

            
            # line_content += f"<p><ul><li>{state_num}</li><li>{action}</li><li>{event_text}</li><li>{view_text}</li><li>{view_description}</li><li>{view_resourceId}</li><li>{view_className}</li></ul></p>\n"
            line_list.append((float(state_num), line_content))

        # 排序并生成最终的 HTML
        line_list.sort()
        new_str += ''.join(item[1] for item in line_list)
        new_str += "   </ul>"
        old_str = "<ul id=\"menu\"></ul>"

        # 读取原始样式文件
        style_content = f_style.read()
        
        # 在 </head> 标签前插入自定义样式
        modified_style = style_content.replace("</head>", f"{custom_style}</head>")
        
        # 写入修改后的 HTML 文件
        f_html.write(modified_style.replace(old_str, new_str))

    

    def is_number(self, str):
        try:
            if str == 'NaN':
                return False
            float(str)
            return True
        except ValueError:
            return False

    def find_action_in_file(self, state_num, lines):
        for line in lines:
            line_num = line[0:line.find("::")]
            if self.is_number(line_num) and self.is_number(state_num):
                if float(state_num) + 1.0 == float(line_num):
                    line = line[line.find("::") + 2 : len(line)]
                    action = line[0:line.find("::")]
                    return state_num + "::" + action
        return state_num

    def print_dividing_line(self, success, event_count, failed_device=None):
        if success is False:
            if failed_device is not None:
                print(f"{event_count} fail device_{failed_device}-------------------")
            else:
                print(f"{event_count} fail device_0-------------------")
        else:
            print(f"{event_count}---------------------------------")

    def generate_outline_html(self, output_path, strategy_list):
        outline_path = output_path + '/all_run_bugs.html'
        f_outline_html = open(outline_path, 'w+', encoding="UTF-8")

        insert_lines = '<!DOCTYPE html>\n' \
                       '<html>\n' \
                       '<head>\n' \
                       '<title>All bug report</title>\n' \
                       '</head>\n' \
                       '<body style="background-color:#F6F6F6">\n'

        tip = "<div style=\"text-align: center\">\n" \
              "<h2>" \
              "This is a bug page that runs the regdroid tool" \
              "</h2>\n" \
              "<h2>All the bug connections are listed below\n" \
              "</h2>\n" \
              "<br/><br/>\n" \
              "-----------------------------------------------------------------------------------" \
              "<br/><br/>\n" \
              "<h3>" \
              "X-Picture:Y means image index(Y) in the test trace(X) of a policy" \
              "</h3>\n" \
              "<h3>" \
              "You can click on it to jump to another detaied page" \
              "</h3>\n" \
              "<br/><br/>\n"
        insert_lines = insert_lines + tip
        bug_index = 1
        for strategy in strategy_list:
            insert_lines = insert_lines + '<div style="text-align: center">'
            directory_num_list = []
            bug_event_num_list = []
            bug_file_name = output_path + "/strategy_" + strategy + "/error_realtime.txt"
            lines = open(bug_file_name, 'r', encoding="UTF-8").readlines()
            step = 2
            lines__ = [lines[i:i + step] for i in range(0, len(lines), step)]
            temp = 0
            for line in lines__:
                find_str1 = "run_count"
                find_str2 = "End"
                if len(line) > 1:
                    if line[0].find(find_str1) > -1:
                        directory_num_list.append(
                            line[0][line[0].find(find_str1) + 11:])
                    elif line[1].find(find_str1) > -1:
                        directory_num_list.append(
                            line[1][line[1].find(find_str1) + 11:])
                    elif line[0].find(find_str2) > -1:
                        bug_event_num_list.append(temp)
                    elif line[1].find(find_str2) > -1:
                        bug_event_num_list.append(
                            line[0][0:line[0].find("::")])
                    temp = line[1][0:4]
                else:
                    if line[0].find(find_str1) > -1:
                        directory_num_list.append(
                            line[0][line[0].find(find_str1) + 11:])
                    elif line[0].find(find_str2) > -1:
                        bug_event_num_list.append(temp)

            if len(directory_num_list) == 0:
                continue

            insert_lines = insert_lines + '<h3> Policy: ' + strategy + '</h3>' + '\n'

            for directory_num, bug_event_num in zip(directory_num_list, bug_event_num_list):
                directory_num = directory_num.strip('\n')
                insert_lines = insert_lines + 'Bug' + str(bug_index) + ': '\
                    '<a href="strategy_' + strategy + '/' + directory_num + '/'+directory_num + "_trace.html" \
                    '" target="_blank" style="text-decoration:underline" >' \
                    + directory_num.replace('\n', '') + \
                    '-Picture:' + bug_event_num + '</a><br/>\n'
                bug_index = bug_index + 1
            insert_lines = insert_lines + '</div>\n' \
                                          '</body>\n' \
                                          '</html>\n'
        f_outline_html.write(''.join(insert_lines))
        f_outline_html.close()

    def generate_replay_all_html(self, output_path, strategy_list):
        outline_path = output_path + '/all_replay_bugs.html'
        f_outline_html = open(outline_path, 'w+', encoding="UTF-8")
        insert_lines = '<!DOCTYPE html>\n' \
                       '<html>\n' \
                       '<head>\n' \
                       '<title>All bug report</title>\n' \
                       '</head>\n' \
                       '<body style="background-color:#F6F6F6">\n'

        tip = "<div style=\"text-align: center\">\n" \
              "<h2>" \
              "This is a bug page that runs the regdroid tool" \
              "</h2>\n" \
              "<h2>All the bug connections are listed below\n" \
              "</h2>\n" \
              "<br/><br/>\n" \
              "-----------------------------------------------------------------------------------" \
              "<br/><br/>\n" \
              "<h3>" \
              "X_trace.html is a bug's hayperlink, you can click on it" \
              "</h3>\n" \
              "<h3>" \
              "And then slide to the last few images to check the bug" \
              "</h3>\n" \
              "<br/><br/>\n"
        insert_lines = insert_lines + tip + '<div style="text-align: center">\n'
        bug_index = 1
        for strategy in strategy_list:

            replay_base_path = output_path + "/strategy_" + strategy + "/error_replay/"
            files = os.listdir(replay_base_path)
            temp_insert_lines = ""
            have_html = False
            for file in files:
                replay_path = replay_base_path + file
                html_files = os.listdir(replay_path)
                have_html = False

                for html in html_files:
                    if html.find('html') > -1:
                        have_html = True
                        temp_insert_lines = temp_insert_lines + 'Bug' + str(bug_index) + ': '\
                            '<a href="strategy_' + strategy + '/error_replay/' + file + '/' + html + \
                            '" target="_blank" style="text-decoration:underline" >' \
                            + html.replace('\n', '') + \
                            '</a><br/>\n'
            if have_html:
                insert_lines = insert_lines + '<h3>Policy: ' + strategy + '</h3>\n'
                insert_lines = insert_lines + temp_insert_lines
                have_html = False
        insert_lines = insert_lines + '</div>\n' \
                                      '</body>\n' \
                                      '</html>\n'
        f_outline_html.write(''.join(insert_lines))
        f_outline_html.close()
