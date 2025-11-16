#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量导出所有实验结果到Excel
"""

import os
import glob
from export_results_to_excel import export_to_excel

# 查找所有JSON结果文件
result_dir = "results/defense_comparison"
json_files = glob.glob(f"{result_dir}/comparison_*.json")

print("=" * 80)
print("📊 批量导出实验结果")
print("=" * 80)
print(f"找到 {len(json_files)} 个结果文件\n")

if not json_files:
    print("❌ 未找到结果文件")
    print(f"   请确保 {result_dir} 目录下有 comparison_*.json 文件")
    exit(1)

# 逐个导出
success_count = 0
for i, json_file in enumerate(json_files, 1):
    print(f"\n[{i}/{len(json_files)}] 处理: {os.path.basename(json_file)}")
    try:
        output_file = export_to_excel(json_file)
        print(f"  ✅ 成功: {os.path.basename(output_file)}")
        success_count += 1
    except Exception as e:
        print(f"  ❌ 失败: {e}")

print("\n" + "=" * 80)
print(f"✅ 完成！成功导出 {success_count}/{len(json_files)} 个文件")
print("=" * 80)
