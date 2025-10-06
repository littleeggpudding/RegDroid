
import logging
import os

from androguard.core.bytecodes.apk import APK


class App(object):

    def __init__(self, app_path, root_path, app_name):
        print("Root path:", root_path)
        assert app_path is not None
        self.logger = logging.getLogger(self.__class__.__name__)
        self.app_path = app_path

        self.apk = APK(self.app_path)
        self.package_name = self.apk.get_package()
        self.main_activity = self.apk.get_main_activity()
        self.permissions = self.apk.get_permissions()
        self.activities = self.apk.get_activities()
        if app_name is not None:
            self.app_name = app_name
        else:
            try:
                self.app_name = self.apk.get_app_name()
            except:
                 # 方法2：使用aapt命令
                try:
                    import subprocess
                    # 尝试获取应用名
                    app_name_cmd = f"aapt dump badging '{self.app_path}' | grep 'application-label:' | awk -F\"'\" '{{print $2}}'"
                    self.app_name = subprocess.check_output(app_name_cmd, shell=True).decode().strip()
                except Exception as e:
                    # 方法3：使用zipfile解析
                    import zipfile
                    import xml.etree.ElementTree as ET
                    
                    with zipfile.ZipFile(self.app_path) as apk:
                        with apk.open('AndroidManifest.xml') as manifest:
                            # 读取并解析manifest文件
                            tree = ET.parse(manifest)
                            root = tree.getroot()
                            
                            # 获取包名
                            self.package_name = root.get('package')
                            
                            # 尝试获取应用名
                            application = root.find('.//application')
                            if application is not None:
                                self.app_name = application.get('{http://schemas.android.com/apk/res/android}label', 'Unknown App')
                            else:
                                self.app_name = 'Unknown App'
        print("Main activity:", self.main_activity)
        print("Package name:", self.package_name)
        self.output_path = os.path.join(root_path, self.package_name)

    def get_package_name(self):
        return self.package_name
