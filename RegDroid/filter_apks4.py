import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re
from collections import Counter

# downloads: 10K+ 50K+ 100K+ 1M+
# stars: > 100
# created_at: <= 2022-10-01

def analyze_stars_distribution(csv_path):
    """
    分析CSV文件中stars列的分布情况
    
    参数:
    csv_path (str): CSV文件路径
    
    返回:
    dict: 包含stars分布的统计信息
    """
    try:
        # 读取CSV文件
        df = pd.read_csv(csv_path)
        
        # 检查是否存在stars列
        if 'stars' not in df.columns:
            print(f"错误：未找到 'stars' 列。可用的列有：{list(df.columns)}")
            return None
        
        # 将stars转换为数值类型（处理可能的非数值情况）
        df['stars'] = pd.to_numeric(df['stars'], errors='coerce')
        
        # 删除可能的空值
        stars_data = df['stars'].dropna()
        
        # 基本统计
        stats = {
            'total_repos': len(stars_data),
            'min_stars': stars_data.min(),
            'max_stars': stars_data.max(),
            'mean_stars': stars_data.mean(),
            'median_stars': stars_data.median(),
        }
        
        # 打印基本统计信息
        print("Stars 分布统计：")
        for key, value in stats.items():
            print(f"{key}: {value}")
        
        # 分段统计
        star_ranges = [
            (0, 10),
            (10, 50),
            (50, 100),
            (100, 500),
            (500, 1000),
            (1000, float('inf'))
        ]
        
        print("\nStars 区间分布：")
        for start, end in star_ranges:
            count = len(stars_data[(stars_data >= start) & (stars_data < end)])
            percentage = count / len(stars_data) * 100
            print(f"{start}-{end if end != float('inf') else '∞'} stars: {count} 个 ({percentage:.2f}%)")
        
        
        return stats
    
    except Exception as e:
        print(f"处理CSV文件时发生错误：{e}")
        return None

def parse_downloads_value(value):
    """
    解析下载量字符串，转换为数值
    支持格式如：'100+', '10M', '5K'等
    """
    if pd.isna(value):
        return np.nan
    
    value = str(value).strip()
    
    # 处理带+的情况
    if value.endswith('+'):
        value = value[:-1]
    
    # 转换K、M等单位
    multipliers = {
        'K': 1000,
        'M': 1000000,
        'B': 1000000000
    }
    
    # 匹配数字和可能的单位
    match = re.match(r'(\d+(?:\.\d+)?)\s*([KMB])?', value, re.IGNORECASE)
    if match:
        num = float(match.group(1))
        unit = match.group(2)
        
        if unit:
            num *= multipliers.get(unit.upper(), 1)
        
        return num
    
    return np.nan

def analyze_string_distribution(csv_path):
    """
    分析CSV文件中downloads和rate列的字符串分布
    
    参数:
    csv_path (str): CSV文件路径
    """
    try:
        # 读取CSV文件
        df = pd.read_csv(csv_path)
        
        # 分析downloads列
        if 'downloads' in df.columns:
            print("\nDownloads 列字符串分布：")
            # 统计原始字符串出现次数
            downloads_counter = Counter(df['downloads'].dropna())
            print("原始字符串分布：")
            for value, count in downloads_counter.most_common(10):
                print(f"{value}: {count} 次")
            
            # 解析并分析数值分布
            df['parsed_downloads'] = df['downloads'].apply(parse_downloads_value)
            downloads_data = df['parsed_downloads'].dropna()
            
            print("\nDownloads 数值分布：")
            print(f"总数：{len(downloads_data)}")
            print(f"最小值：{downloads_data.min()}")
            print(f"最大值：{downloads_data.max()}")
            print(f"平均值：{downloads_data.mean():.2f}")
            print(f"中位数：{downloads_data.median():.2f}")
            
            # 分段统计
            download_ranges = [
                (0, 1000),
                (1000, 10000),
                (10000, 100000),
                (100000, 1000000),
                (1000000, float('inf'))
            ]
            
            print("\nDownloads 区间分布：")
            for start, end in download_ranges:
                count = len(downloads_data[(downloads_data >= start) & (downloads_data < end)])
                percentage = count / len(downloads_data) * 100
                print(f"{start}-{end if end != float('inf') else '∞'}: {count} 个 ({percentage:.2f}%)")
        
        # 分析rate列
        if 'rate' in df.columns:
            print("\nRate 列字符串分布：")
            # 统计原始字符串出现次数
            rate_counter = Counter(df['rate'].dropna())
            print("原始字符串分布：")
            for value, count in rate_counter.most_common(10):
                print(f"{value}: {count} 次")
            
            # 尝试转换为数值（如果可能）
            df['parsed_rate'] = pd.to_numeric(df['rate'], errors='coerce')
            rate_data = df['parsed_rate'].dropna()
            
            if len(rate_data) > 0:
                print("\nRate 数值分布：")
                print(f"总数：{len(rate_data)}")
                print(f"最小值：{rate_data.min()}")
                print(f"最大值：{rate_data.max()}")
                print(f"平均值：{rate_data.mean():.2f}")
                print(f"中位数：{rate_data.median():.2f}")
    
    except Exception as e:
        print(f"处理CSV文件时发生错误：{e}")

def filter_and_analyze_repos(csv_path):
    """
    筛选并分析符合特定条件的仓库
    
    参数:
    csv_path (str): CSV文件路径
    """
    try:
        # 读取CSV文件
        df = pd.read_csv(csv_path)
        
        # 定义下载量阈值
        download_thresholds = ['10K+', '50K+', '100K+', '1M+']
        
        # 筛选条件：下载量在阈值以上且stars > 100的仓库
        filtered_repos = df[
            (df['downloads'].isin(download_thresholds)) &  # 直接匹配下载量字符串
            (df['stars'] > 100) &
            (df['created_at'] <= '2022-10-01')
        ]
        
        # 打印总数
        print(f"\n符合条件的仓库总数：{len(filtered_repos)}")
        
        # 分析rate分布
        if 'rate' in filtered_repos.columns:
            print("\nRate 列分布：")
            rate_counter = Counter(filtered_repos['rate'].dropna())
            print("原始字符串分布：")
            for value, count in rate_counter.most_common(10):
                print(f"{value}: {count} 次")
            
            # 尝试转换为数值
            filtered_repos['parsed_rate'] = pd.to_numeric(filtered_repos['rate'], errors='coerce')
            rate_data = filtered_repos['parsed_rate'].dropna()
            
            if len(rate_data) > 0:
                print("\nRate 数值分布：")
                print(f"总数：{len(rate_data)}")
                print(f"最小值：{rate_data.min()}")
                print(f"最大值：{rate_data.max()}")
                print(f"平均值：{rate_data.mean():.2f}")
                print(f"中位数：{rate_data.median():.2f}")
        
        # 输出到CSV
        output_csv_path = 'android_repos_with_high_downloads_high_stars.csv'
        filtered_repos.to_csv(output_csv_path, index=False)
        print(f"\n已将符合条件的仓库导出到 {output_csv_path}")
        
        return filtered_repos
    
    except Exception as e:
        print(f"处理CSV文件时发生错误：{e}")
        return None

def main():
    # 可以在这里指定CSV文件路径
    csv_path = 'android_repos_with_google_play.csv'  # 请根据实际文件名修改
    filter_and_analyze_repos(csv_path)

if __name__ == '__main__':
    main()
