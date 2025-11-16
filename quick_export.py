#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
快速导出工具 - 指定文件路径
"""

from export_results_to_excel import export_to_excel

# 指定你的结果文件路径
json_file = r"results\defense_comparison\comparison_poisonedfl_mr40_20251113_200040.json"

# 导出
print("开始导出...")
output_file = export_to_excel(json_file)
print(f"完成！Excel文件: {output_file}")
