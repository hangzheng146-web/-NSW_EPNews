import os
import pandas as pd

def is_30min_sampling(filepath):
    """
    检查 CSV 文件中 SETTLEMENTDATE 列的时间间隔是否均为 30 分钟。
    返回：
      (True, None)  如果所有相邻时间间隔均为 30 分钟，
      (False, error_msg) 否则
    """
    try:
        df = pd.read_csv(filepath, parse_dates=["SETTLEMENTDATE"])
        if "SETTLEMENTDATE" not in df.columns:
            return False, "缺少 SETTLEMENTDATE 列。"
        if df.shape[0] < 2:
            return False, "数据行数不足，无法判断采样间隔。"
        df = df.sort_values("SETTLEMENTDATE")
        diffs = df["SETTLEMENTDATE"].diff().dropna()
        if (diffs == pd.Timedelta("30T")).all():
            return True, None
        else:
            unique_diffs = diffs.unique()
            return False, f"发现不同的间隔：{unique_diffs}"
    except Exception as e:
        return False, f"读取或处理文件时出错：{e}"

def check_periodtype(filepath):
    """
    检查 CSV 文件的 PERIODTYPE 列是否仅包含 "TRADE" 值。
    如果 PERIODTYPE 列中存在除 "TRADE" 以外的其他值，则返回 (False, error_msg)；
    否则返回 (True, None)。
    """
    try:
        df = pd.read_csv(filepath, usecols=["PERIODTYPE"])
        # 将所有值转换为字符串（并去除前后空格）后判断唯一值集合
        unique_values = set(df["PERIODTYPE"].astype(str).str.strip())
        if unique_values != {"TRADE"}:
            non_trade = unique_values - {"TRADE"}
            return False, f"存在非 TRADE 的值：{non_trade}"
        else:
            return True, None
    except Exception as e:
        return False, f"读取或处理 PERIODTYPE 列时出错：{e}"

def count_and_check_csv_files(root_folders):
    """
    遍历指定顶级文件夹及其子目录：
      - 统计 CSV 文件总数量；
      - 检查每个 CSV 文件的 SETTLEMENTDATE 列采样是否为 30 分钟一采样；
      - 检查每个 CSV 文件的 PERIODTYPE 列是否仅包含 "TRADE" 值；
      - 统计所有 CSV 文件的总行数（不包括表头）。
    返回：
      total_csv_files: CSV 文件总数量
      valid_sampling_count: 满足 30 分钟采样要求的文件数量
      invalid_sampling_files: 列表，包含采样不符合要求的 (文件路径, 错误说明)
      invalid_periodtype_files: 列表，包含 PERIODTYPE 异常的 (文件路径, 错误说明)
      total_rows: 所有 CSV 文件的行数总和（不含表头）
    """
    total_csv_files = 0
    valid_sampling_count = 0
    invalid_sampling_files = []
    invalid_periodtype_files = []
    total_rows = 0
    
    for folder in root_folders:
        for current_dir, _, files in os.walk(folder):
            for file in files:
                if file.lower().endswith(".csv"):
                    total_csv_files += 1
                    file_path = os.path.join(current_dir, file)
                    
                    # 检查 30 分钟采样情况
                    valid_sample, error_sample = is_30min_sampling(file_path)
                    if valid_sample:
                        valid_sampling_count += 1
                    else:
                        invalid_sampling_files.append((file_path, error_sample))
                    
                    # 检查 PERIODTYPE 列是否仅包含 "TRADE"
                    valid_period, error_period = check_periodtype(file_path)
                    if not valid_period:
                        invalid_periodtype_files.append((file_path, error_period))
                    
                    # 统计文件行数（不含表头）
                    try:
                        df_rows = pd.read_csv(file_path)
                        total_rows += df_rows.shape[0]
                    except Exception as e:
                        print(f"读取文件 {file_path} 统计行数时出错：{e}")
                        
    return total_csv_files, valid_sampling_count, invalid_sampling_files, invalid_periodtype_files, total_rows

if __name__ == "__main__":
    # 指定需要遍历的顶级文件夹列表，例如 "2021", "2022", "2023", "2024"
    top_level_folders = ["2021", "2022", "2023", "2024","2015","2016","2017","2018","2019","2020"]
    
    # 检查顶级文件夹是否存在
    missing = [folder for folder in top_level_folders if not os.path.exists(folder)]
    if missing:
        print(f"以下文件夹不存在：{missing}")
    
    # 统计 CSV 文件总数、检查采样、检查 PERIODTYPE 列，并统计所有 CSV 文件总行数
    total, valid_sampling_count, invalid_sampling_files, invalid_periodtype_files, total_rows = count_and_check_csv_files(top_level_folders)
    
    print(f"共找到 {total} 个 CSV 文件。")
    if total == 600:
        print("CSV 文件数量等于600个。")
    else:
        print("CSV 文件数量不等于600个。")
    
    print(f"所有 CSV 文件加起来总共有 {total_rows} 行数据。")
    print(f"其中有 {valid_sampling_count} 个 CSV 文件满足每30分钟采样要求。")
    
    if invalid_sampling_files:
        print("\n以下文件不满足30分钟采样要求：")
        for file_path, error in invalid_sampling_files:
            print(f"{file_path} => {error}")
    else:
        print("\n所有 CSV 文件均满足30分钟采样要求。")
    
    if invalid_periodtype_files:
        print("\n以下文件的 PERIODTYPE 列存在非 TRADE 的值：")
        for file_path, error in invalid_periodtype_files:
            print(f"{file_path} => {error}")
    else:
        print("\n所有 CSV 文件的 PERIODTYPE 列均仅包含 TRADE 值。")
