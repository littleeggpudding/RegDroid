#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import cv2
import numpy as np
import xml.etree.ElementTree as ET
import re
from typing import Dict, List, Tuple, Optional
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Rectangle

class ReplayAnalyzer:
    def __init__(self, data_path: str):
        """
        初始化Replay分析器
        
        Args:
            data_path: 包含screen文件夹和read_trace.txt的路径
        """
        self.data_path = data_path
        self.screen_path = os.path.join(data_path, "screen")
        self.trace_file = os.path.join(data_path, "read_trace.txt")
        
        # 加载轨迹数据
        self.trace_data = self._load_trace_data()
        
        # 获取所有状态图片
        self.state_images = self._get_state_images()
        
    def _load_trace_data(self) -> List[Dict]:
        """加载轨迹数据"""
        trace_data = []
        
        if not os.path.exists(self.trace_file):
            print(f"Warning: {self.trace_file} not found")
            return trace_data
            
        with open(self.trace_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                    
                parts = line.split("::")
                if len(parts) >= 8:
                    trace_data.append({
                        'action_id': parts[0],
                        'action': parts[1],
                        'device': parts[2],
                        'event_text': parts[3],
                        'view_text': parts[4],
                        'view_description': parts[5],
                        'view_resourceId': parts[6],
                        'view_className': parts[7].strip(),
                        'view_bounds': parts[8].strip() if len(parts) >= 9 else None
                    })
        
        return trace_data
    
    def _get_state_images(self) -> Dict[str, List[str]]:
        """获取所有状态图片"""
        state_images = {}
        
        if not os.path.exists(self.screen_path):
            print(f"Warning: {self.screen_path} not found")
            return state_images
            
        for filename in os.listdir(self.screen_path):
            if filename.endswith('.png'):
                # 提取状态编号 (例如: 3.0_emulator-5554.png -> 3.0)
                state_num = filename.split('_')[0]
                if state_num not in state_images:
                    state_images[state_num] = []
                state_images[state_num].append(filename)
        
        return state_images
    
    def _parse_bounds(self, bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
        """解析bounds字符串，返回(x1, y1, x2, y2)"""
        if not bounds_str or bounds_str == "None":
            return None
            
        # 解析格式: [x1,y1][x2,y2]
        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
        if match:
            return tuple(map(int, match.groups()))
        return None
    
    def _find_widget_in_xml(self, xml_file: str, resource_id: str, class_name: str, target_bounds: str = None) -> Optional[Dict]:
        """在XML文件中查找指定的widget，优先使用bounds匹配"""
        if not os.path.exists(xml_file):
            return None
            
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            
            # 如果提供了目标bounds，先尝试精确匹配
            if target_bounds:
                target_bounds_parsed = self._parse_bounds(target_bounds)
                if target_bounds_parsed:
                    for node in root.iter():
                        node_bounds = node.get('bounds', '')
                        if node_bounds == target_bounds:
                            # 找到bounds完全匹配的节点，验证其他属性
                            node_resource_id = node.get('resource-id', '')
                            node_class = node.get('class', '')
                            
                            # 如果resource_id和class_name也匹配，返回这个节点
                            if (not resource_id or resource_id in node_resource_id) and \
                               (not class_name or class_name in node_class):
                                return {
                                    'bounds': target_bounds_parsed,
                                    'text': node.get('text', ''),
                                    'content_desc': node.get('content-desc', ''),
                                    'clickable': node.get('clickable', 'false') == 'true',
                                    'enabled': node.get('enabled', 'false') == 'true'
                                }
            
            # 如果没有bounds匹配或没有提供bounds，使用原来的逻辑
            for node in root.iter():
                node_resource_id = node.get('resource-id', '')
                node_class = node.get('class', '')
                node_bounds = node.get('bounds', '')
                node_text = node.get('text', '')
                node_content_desc = node.get('content-desc', '')
                
                # 匹配resource-id和class
                if (resource_id in node_resource_id and 
                    class_name in node_class and
                    node_bounds):
                    
                    bounds = self._parse_bounds(node_bounds)
                    if bounds:
                        return {
                            'bounds': bounds,
                            'text': node_text,
                            'content_desc': node_content_desc,
                            'clickable': node.get('clickable', 'false') == 'true',
                            'enabled': node.get('enabled', 'false') == 'true'
                        }
        except Exception as e:
            print(f"Error parsing XML {xml_file}: {e}")
            
        return None
    
    def _get_widget_bounds(self, state_num: str, resource_id: str, class_name: str, target_bounds: str = None) -> Optional[Tuple[int, int, int, int]]:
        """获取指定widget的边界框，优先使用bounds匹配"""
        # 查找对应状态的XML文件
        xml_files = [f for f in os.listdir(self.screen_path) 
                    if f.startswith(f"{state_num}_") and f.endswith('.xml')]
        
        for xml_file in xml_files:
            xml_path = os.path.join(self.screen_path, xml_file)
            widget_info = self._find_widget_in_xml(xml_path, resource_id, class_name, target_bounds)
            if widget_info:
                return widget_info['bounds']
        
        return None
    
    def _draw_green_box(self, image: np.ndarray, bounds: Tuple[int, int, int, int], 
                       success: bool = True) -> np.ndarray:
        """在图像上绘制绿色框"""
        x1, y1, x2, y2 = bounds
        
        # 创建图像副本
        result_image = image.copy()
        
        # 绘制绿色框
        color = (0, 255, 0) if success else (0, 0, 255)  # 绿色表示成功，红色表示失败
        thickness = 3
        
        cv2.rectangle(result_image, (x1, y1), (x2, y2), color, thickness)
        
        # 添加状态文本
        status_text = "TRUE" if success else "FALSE"
        text_color = (0, 255, 0) if success else (0, 0, 255)
        
        # 在框的上方添加文本
        text_x = x1
        text_y = max(y1 - 10, 20)
        
        cv2.putText(result_image, status_text, (text_x, text_y), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, text_color, 2)
        
        return result_image
    
    def replay_action(self, state_num: str, action_info: Dict) -> Tuple[bool, Optional[np.ndarray]]:
        """
        重放单个动作
        
        Args:
            state_num: 状态编号
            action_info: 动作信息
            
        Returns:
            (是否成功, 标注后的图像)
        """
        resource_id = action_info.get('view_resourceId', '')
        class_name = action_info.get('view_className', '')
        target_bounds = action_info.get('view_bounds', '')
        action = action_info.get('action', '')
        
        print(f"Replaying action {action} on state {state_num}")
        print(f"Looking for widget: {resource_id} ({class_name})")
        if target_bounds:
            print(f"Target bounds: {target_bounds}")
        
        # 查找widget边界，优先使用bounds信息
        bounds = self._get_widget_bounds(state_num, resource_id, class_name, target_bounds)
        
        if bounds is None:
            print(f"FALSE: Widget not found")
            return False, None
        
        print(f"Widget found at bounds: {bounds}")
        
        # 获取对应的图片
        image_files = [f for f in os.listdir(self.screen_path) 
                      if f.startswith(f"{state_num}_") and f.endswith('.png')]
        
        if not image_files:
            print(f"FALSE: No image found for state {state_num}")
            return False, None
        
        # 使用第一个找到的图片
        image_path = os.path.join(self.screen_path, image_files[0])
        image = cv2.imread(image_path)
        
        if image is None:
            print(f"FALSE: Cannot load image {image_path}")
            return False, None
        
        # 绘制绿色框
        annotated_image = self._draw_green_box(image, bounds, True)
        
        print(f"TRUE: Action can be replayed")
        return True, annotated_image
    
    def replay_all_actions(self) -> Dict[str, Tuple[bool, Optional[np.ndarray]]]:
        """重放所有动作"""
        results = {}
        
        print("=== Starting Replay Analysis ===")
        
        # 按状态编号排序
        sorted_states = sorted(self.state_images.keys(), key=float)
        
        for state_num in sorted_states:
            print(f"\n--- Processing State {state_num} ---")
            
            # 查找对应的动作
            action_info = None
            for trace in self.trace_data:
                action_id = trace['action_id']
                if float(state_num) + 1.0 == float(action_id):
                    action_info = trace
                    break
            
            if action_info is None:
                print(f"No action found for state {state_num}")
                results[state_num] = (False, None)
                continue
            
            # 重放动作
            success, annotated_image = self.replay_action(state_num, action_info)
            results[state_num] = (success, annotated_image)
        
        return results
    
    def save_results(self, results: Dict[str, Tuple[bool, Optional[np.ndarray]]], 
                    output_dir: str = None):
        """保存结果图像"""
        if output_dir is None:
            output_dir = os.path.join(self.data_path, "replay_results")
        
        os.makedirs(output_dir, exist_ok=True)
        
        for state_num, (success, image) in results.items():
            if image is not None:
                output_path = os.path.join(output_dir, f"state_{state_num}_replay.png")
                cv2.imwrite(output_path, image)
                print(f"Saved result for state {state_num}: {output_path}")
    
    def generate_summary_report(self, results: Dict[str, Tuple[bool, Optional[np.ndarray]]]):
        """生成总结报告"""
        total_states = len(results)
        successful_states = sum(1 for success, _ in results.values() if success)
        failed_states = total_states - successful_states
        
        print("\n" + "="*50)
        print("REPLAY SUMMARY REPORT")
        print("="*50)
        print(f"Total states analyzed: {total_states}")
        print(f"Successful replays: {successful_states}")
        print(f"Failed replays: {failed_states}")
        print(f"Success rate: {successful_states/total_states*100:.1f}%")
        
        print("\nDetailed Results:")
        for state_num, (success, _) in results.items():
            status = "TRUE" if success else "FALSE"
            print(f"  State {state_num}: {status}")

def main():
    """主函数"""
    # 设置数据路径
    data_path = "/Users/ssw/Downloads/RegDroid/Output/com.amaze.filemanager/strategy_test_results/1"
    
    # 创建分析器
    analyzer = ReplayAnalyzer(data_path)
    
    # 执行重放分析
    results = analyzer.replay_all_actions()
    
    # 保存结果
    analyzer.save_results(results)
    
    # 生成报告
    analyzer.generate_summary_report(results)

if __name__ == "__main__":
    main()
