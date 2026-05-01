import os
import pandas as pd

def process_file(filepath):
    try:
        # 1. 读取 CSV 文件，同时解析 SETTLEMENTDATE 为日期时间类型
        df_original = pd.read_csv(filepath, parse_dates=["SETTLEMENTDATE"])
        
        # 保存原始的列顺序
        original_columns = df_original.columns.tolist()
        
        # 2. 将 SETTLEMENTDATE 列设置为索引，便于重采样
        df = df_original.copy()
        df.set_index("SETTLEMENTDATE", inplace=True)
        
        # 3. 定义重采样的聚合规则：
        #    - RRP：取中位数
        #    - TOTALDEMAND：取平均值
        #    - 其他列（例如 REGION、PERIODTYPE）：取每个半小时内的第一个值
        aggregation_rules = {
            "RRP": "median",
            "TOTALDEMAND": "mean",
            "REGION": "first",
            "PERIODTYPE": "first"
        }
        
        # 4. 对数据进行重采样：以 30 分钟为间隔，
        #    label="right" 表示以每个区间的右边界作为标签，
        #    closed="right" 表示区间右闭，即 (00:00,00:30] 这样的区间
        df_resampled = df.resample("30T", label="right", closed="right").agg(aggregation_rules)
        
        # 5. 重置索引，将 SETTLEMENTDATE 恢复为普通列，然后调整列顺序与原文件保持一致
        df_resampled.reset_index(inplace=True)
        df_resampled = df_resampled[original_columns]
        
        # 6. 构造输出文件名，输出文件与原文件放在相同目录，文件名前加 "NEW_"
        dir_name = os.path.dirname(filepath)
        base_name = os.path.basename(filepath)
        new_filename = os.path.join(dir_name, "NEW_" + base_name)
        
        # 7. 保存结果到 CSV 文件
        df_resampled.to_csv(new_filename, index=False)
        print(f"处理完成，已生成：{new_filename}")
    except Exception as e:
        print(f"处理文件 {filepath} 时出错：{e}")

def process_folder(root_folder):
    # 遍历给定文件夹及其子文件夹
    for current_dir, dirs, files in os.walk(root_folder):
        for file in files:
            # 只处理扩展名为 .csv 且文件名不以 NEW_ 开头的文件
            if file.lower().endswith(".csv") and not file.startswith("NEW_"):
                file_path = os.path.join(current_dir, file)
                process_file(file_path)

if __name__ == "__main__":
    # 指定要处理的顶级文件夹列表
    top_level_folders = ["2021", "2022", "2023", "2024"]

    for folder in top_level_folders:
        if os.path.exists(folder) and os.path.isdir(folder):
            print(f"正在处理文件夹: {folder}")
            process_folder(folder)
        else:
            print(f"文件夹 {folder} 不存在或不是目录。")
