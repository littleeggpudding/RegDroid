import re

def check_log_continuity(log_file_path, total_lines=309):
    # 用于存储所有行号
    line_numbers = set()

    # 正则表达式匹配 LINE 后的数字
    pattern = re.compile(r'LINE (\d+)')

    # 读取日志文件
    with open(log_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            match = pattern.search(line)
            if match:
                line_numbers.add(int(match.group(1)))

    # 如果没有行号，直接返回
    if not line_numbers:
        print("日志中没有找到行号")
        return

    # 找出最大行号
    max_line = max(line_numbers)
    print(f"最大行号: {max_line}")

    # 检查连续性，找出1到total_lines中缺失的行号
    missing_lines = []
    for i in range(1, total_lines + 1):
        if i not in line_numbers:
            missing_lines.append(i)

    # 输出结果到 check_log.log
    with open('check_log.log', 'w', encoding='utf-8') as f:
        f.write(f"总行数: {total_lines}\n")
        f.write(f"最大行号: {max_line}\n")
        f.write(f"缺失行数: {len(missing_lines)}\n\n")
        f.write("缺失的行号:\n")
        
        # 分批写入，避免一次性写入太多
        for i in range(0, len(missing_lines), 1000):
            batch = missing_lines[i:i+1000]
            f.write(','.join(map(str, batch)) + '\n')

    # 控制台输出摘要
    print(f"缺失行数: {len(missing_lines)}")
    print(f"详细缺失行号已写入 check_log.log")

if __name__ == "__main__":
    check_log_file = 'filter_repos5.log'  # 默认日志文件名
    check_log_continuity(check_log_file)