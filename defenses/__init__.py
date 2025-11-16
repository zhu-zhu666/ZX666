"""
防御机制模块

包含各种联邦学习防御方法：
- FLTrust: 基于信任分数的拜占庭鲁棒聚合 (NeurIPS 2020)
- 其他基线防御方法
"""

from .fltrust import FLTrust, create_root_dataset

__all__ = ['FLTrust', 'create_root_dataset']
