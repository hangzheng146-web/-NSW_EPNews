import pandas as pd

# 1. 读取 CSV 文件，同时解析SETTLEMENTDATE为日期时间类型
df_original = pd.read_csv("PRICE_AND_DEMAND_202110_NSW1.csv", parse_dates=["SETTLEMENTDATE"])

# 保存原始的列顺序
original_columns = df_original.columns.tolist()

# 2. 将 SETTLEMENTDATE 列设置为索引便于重采样
df = df_original.copy()
df = df.set_index("SETTLEMENTDATE")

# 3. 定义重采样时的聚合规则
#    - RRP列：取中位数
#    - TOTALDEMAND列：取平均值
#    - 其他列：取每个时间段内的第一个值（假设在同一时间段内不变）
aggregation_rules = {
    "RRP": "median",
    "TOTALDEMAND": "mean",
    "REGION": "first",
    "PERIODTYPE": "first"
}

## 4. 使用 30 分钟的重采样频率，并指定：
#    label="right": 以每个区间的右边界作为标签（如 00:30、01:00 等）
#    closed="right": 区间为右闭区间，即 (00:00, 00:30]，使得 00:30 这一时刻包含在内
df_resampled = df.resample("30T", label="right", closed="right").agg(aggregation_rules)

# 5. 重置索引，将 SETTLEMENTDATE 还原为普通列，然后按照原始的列顺序排序
df_resampled = df_resampled.reset_index()
df_resampled = df_resampled[original_columns]

# 7. 将结果保存为新的 CSV 文件
df_resampled.to_csv("2new_PRICE_AND_DEMAND_202110_NSW1.csv", index=False)

print("数据重采样完成，并已保存为 '2new_PRICE_AND_DEMAND_202110_NSW1.csv'。")
