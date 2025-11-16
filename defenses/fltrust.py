"""
FLTrust: Byzantine-robust Federated Learning via Trust Bootstrapping

论文：FLTrust: Byzantine-robust Federated Learning via Trust Bootstrapping (NeurIPS 2020)
作者：Xiaoyu Cao, Minghong Fang, Jia Liu, Neil Zhenqiang Gong
链接：https://arxiv.org/abs/2012.13995

核心思想：
1. 服务器维护一个小的根数据集（root dataset），这是可信的干净数据
2. 在每轮聚合前，服务器在根数据集上计算自己的更新（作为可信基准）
3. 计算客户端更新与服务器更新的余弦相似度作为信任分数（Trust Score）
4. 使用ReLU归一化的信任分数：TS_i = max(0, cos_similarity(g_i, g_0))
5. 将所有客户端更新归一化到与服务器更新相同的范数（防止放大攻击）
6. 使用信任分数加权平均进行聚合

关键防御机制：
- Trust Score: 方向偏离越大，信任分数越低
- Normalization: 限制恶意更新的幅度影响
- ReLU Clipping: 过滤反方向的恶意更新
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from typing import Dict, List, Tuple, Optional
import copy


class FLTrust:
    """
    FLTrust防御机制实现
    
    使用服务器端的根数据集评估客户端更新的可信度，
    并基于信任分数进行鲁棒聚合。
    
    参数：
    ----------
    root_dataset : torch.utils.data.Dataset
        服务器端的干净根数据集，用于计算可信更新
        
    device : str
        计算设备 ('cpu' 或 'cuda')
        
    clip_threshold : float, default=0.0
        信任阈值，使用ReLU(cos_sim)，默认为0
        
    Examples:
    ----------
    >>> # 创建FLTrust防御
    >>> fltrust = FLTrust(root_dataset=server_dataset, device='cuda')
    >>> 
    >>> # 聚合客户端更新
    >>> global_update = fltrust.aggregate(
    ...     global_model=global_model,
    ...     client_updates=client_updates,
    ...     learning_rate=0.01
    ... )
    """
    
    def __init__(self, 
                 root_dataset,
                 device: str = 'cpu',
                 clip_threshold: float = 0.0):
        """
        初始化FLTrust防御
        
        参数：
        ----------
        root_dataset : torch.utils.data.Dataset
            服务器端的干净根数据集
            
        device : str
            计算设备
            
        clip_threshold : float
            ReLU阈值，默认为0（原论文设置）
        """
        if root_dataset is None or len(root_dataset) == 0:
            raise ValueError("根数据集不能为空")
            
        self.root_dataset = root_dataset
        self.device = device
        self.clip_threshold = clip_threshold
        
        print(f"[FLTrust] 初始化完成")
        print(f"  - 根数据集大小: {len(root_dataset)}")
        print(f"  - 设备: {device}")
        print(f"  - ReLU阈值: {clip_threshold}")
    
    def compute_server_update(self,
                             global_model: nn.Module,
                             criterion: nn.Module,
                             learning_rate: float,
                             batch_size: int = 64,
                             num_steps: int = 10) -> Dict[str, torch.Tensor]:
        """
        在根数据集上计算服务器的可信更新
        
        算法：
        1. 保存当前全局模型参数
        2. 在根数据集上训练一步（或多步）
        3. 计算更新 = 新参数 - 旧参数
        4. 恢复全局模型到原始状态
        
        参数：
        ----------
        global_model : nn.Module
            当前全局模型
            
        criterion : nn.Module
            损失函数
            
        learning_rate : float
            学习率
            
        batch_size : int
            批大小
            
        num_steps : int
            训练步数（默认1步，与论文一致）
            
        返回：
        ----------
        server_update : Dict[str, torch.Tensor]
            服务器更新（参数差）
        """
        # 保存原始模型参数
        original_state = copy.deepcopy(global_model.state_dict())
        
        # 设置为训练模式
        global_model.train()
        
        # 创建优化器（与客户端训练保持一致：lr + momentum=0.9）
        optimizer = torch.optim.SGD(global_model.parameters(), lr=learning_rate, momentum=0.9)
        
        # 创建DataLoader
        root_loader = DataLoader(
            self.root_dataset,
            batch_size=min(batch_size, len(self.root_dataset)),
            shuffle=True
        )
        
        # 训练num_steps步
        steps = 0
        for _ in range(num_steps):
            for data, target in root_loader:
                data, target = data.to(self.device), target.to(self.device)
                
                optimizer.zero_grad()
                output = global_model(data)
                
                # 处理字典格式的输出（如LeNet5）
                if isinstance(output, dict):
                    output = output['output']
                
                loss = criterion(output, target)
                loss.backward()
                optimizer.step()
                
                steps += 1
                if steps >= num_steps:
                    break
            if steps >= num_steps:
                break
        
        # 计算更新（新参数 - 旧参数）
        server_update = {}
        current_state = global_model.state_dict()
        for name in original_state.keys():
            if 'weight' in name or 'bias' in name:  # 只考虑权重和偏置
                server_update[name] = current_state[name] - original_state[name]
        
        # 恢复原始模型
        global_model.load_state_dict(original_state)
        
        return server_update
    
    def _flatten_params(self, params_dict: Dict[str, torch.Tensor]) -> torch.Tensor:
        """
        将参数字典展平为一维向量
        
        参数：
        ----------
        params_dict : Dict[str, torch.Tensor]
            参数字典
            
        返回：
        ----------
        flattened : torch.Tensor
            展平的一维向量
        """
        return torch.cat([p.flatten() for p in params_dict.values()])
    
    def compute_trust_scores(self,
                           client_updates: List[Dict[str, torch.Tensor]],
                           server_update: Dict[str, torch.Tensor]) -> np.ndarray:
        """
        计算客户端更新的信任分数
        
        算法（FLTrust核心）：
        1. 将更新展平成向量
        2. 计算余弦相似度: cos_sim = <v_c, v_s> / (||v_c|| * ||v_s||)
        3. 应用ReLU: trust_score = max(0, cos_sim)
        
        参数：
        ----------
        client_updates : List[Dict[str, torch.Tensor]]
            客户端更新列表
            
        server_update : Dict[str, torch.Tensor]
            服务器的可信更新
            
        返回：
        ----------
        trust_scores : np.ndarray
            每个客户端的信任分数，shape: (num_clients,)
        """
        # 展平服务器更新
        server_vec = self._flatten_params(server_update)
        server_norm = torch.norm(server_vec)
        
        if server_norm == 0:
            raise ValueError("服务器更新范数为0，无法计算信任分数")
        
        trust_scores = []
        
        for client_update in client_updates:
            # 展平客户端更新
            client_vec = self._flatten_params(client_update)
            client_norm = torch.norm(client_vec)
            
            if client_norm == 0:
                # 如果客户端更新为0，信任分数设为0
                trust_scores.append(0.0)
                continue
            
            # 计算余弦相似度
            cos_sim = torch.dot(server_vec, client_vec) / (server_norm * client_norm)
            
            # ReLU裁剪
            trust_score = max(0.0, cos_sim.item())
            trust_scores.append(trust_score)
        
        return np.array(trust_scores)
    
    def normalize_updates(self,
                         client_updates: List[Dict[str, torch.Tensor]],
                         server_update: Dict[str, torch.Tensor]) -> List[Dict[str, torch.Tensor]]:
        """
        归一化客户端更新到服务器更新的范数
        
        算法：
        归一化后的更新 = (||g_0|| / ||g_i||) * g_i
        
        这将所有更新投影到同一超球面，限制恶意更新的幅度影响
        
        参数：
        ----------
        client_updates : List[Dict[str, torch.Tensor]]
            客户端更新列表
            
        server_update : Dict[str, torch.Tensor]
            服务器更新
            
        返回：
        ----------
        normalized_updates : List[Dict[str, torch.Tensor]]
            归一化后的客户端更新
        """
        # 计算服务器更新的范数
        server_vec = self._flatten_params(server_update)
        server_norm = torch.norm(server_vec).item()
        
        if server_norm == 0:
            raise ValueError("服务器更新范数为0，无法归一化")
        
        normalized_updates = []
        
        for client_update in client_updates:
            # 计算客户端更新的范数
            client_vec = self._flatten_params(client_update)
            client_norm = torch.norm(client_vec).item()
            
            if client_norm == 0:
                # 如果客户端更新为0，保持为0
                normalized_updates.append(client_update)
                continue
            
            # 归一化因子
            scale = server_norm / client_norm
            
            # 归一化每个参数
            normalized_update = {}
            for name, param in client_update.items():
                normalized_update[name] = param * scale
            
            normalized_updates.append(normalized_update)
        
        return normalized_updates
    
    def aggregate(self,
                 global_model: nn.Module,
                 client_updates: List[Dict[str, torch.Tensor]],
                 criterion: nn.Module,
                 learning_rate: float,
                 batch_size: int = 64,
                 num_steps: int = 10) -> Dict[str, torch.Tensor]:
        """
        FLTrust聚合算法（主函数）
        
        完整流程：
        1. 计算服务器可信更新
        2. 计算每个客户端的信任分数
        3. 归一化所有客户端更新
        4. 加权平均聚合
        
        参数：
        ----------
        global_model : nn.Module
            全局模型
            
        client_updates : List[Dict[str, torch.Tensor]]
            客户端更新列表
            
        criterion : nn.Module
            损失函数
            
        learning_rate : float
            学习率
            
        batch_size : int
            根数据集批大小
            
        返回：
        ----------
        aggregated_update : Dict[str, torch.Tensor]
            聚合后的全局更新
        """
        if len(client_updates) == 0:
            raise ValueError("客户端更新列表为空")
        
        # 步骤1: 计算服务器更新
        server_update = self.compute_server_update(
            global_model=global_model,
            criterion=criterion,
            learning_rate=learning_rate,
            batch_size=batch_size,
            num_steps=num_steps
        )
        
        # 步骤2: 计算信任分数
        trust_scores = self.compute_trust_scores(
            client_updates=client_updates,
            server_update=server_update
        )
        
        # 打印信任分数统计
        print(f"[FLTrust] 信任分数统计:")
        print(f"  - 平均: {np.mean(trust_scores):.4f}")
        print(f"  - 最小: {np.min(trust_scores):.4f}")
        print(f"  - 最大: {np.max(trust_scores):.4f}")
        print(f"  - 零信任分数客户端: {np.sum(trust_scores == 0)}/{len(trust_scores)}")
        
        # 步骤3: 归一化客户端更新
        normalized_updates = self.normalize_updates(
            client_updates=client_updates,
            server_update=server_update
        )
        
        # 步骤4: 加权平均聚合
        # 计算信任分数总和
        total_trust = np.sum(trust_scores)
        
        if total_trust == 0:
            print("[FLTrust] 警告: 所有客户端信任分数为0，使用均匀权重")
            weights = np.ones(len(trust_scores)) / len(trust_scores)
        else:
            weights = trust_scores / total_trust
        
        # 聚合
        aggregated_update = {}
        param_names = list(normalized_updates[0].keys())
        
        for name in param_names:
            # 加权求和
            weighted_sum = torch.zeros_like(normalized_updates[0][name])
            for i, update in enumerate(normalized_updates):
                weighted_sum += weights[i] * update[name]
            
            aggregated_update[name] = weighted_sum
        
        return aggregated_update, trust_scores
    
    def aggregate_models(self,
                        global_model: nn.Module,
                        client_models: List[nn.Module],
                        criterion: nn.Module,
                        learning_rate: float,
                        batch_size: int = 64,
                        num_steps: int = 10) -> Tuple[Dict[str, torch.Tensor], np.ndarray]:
        """
        从客户端模型聚合（便捷接口）
        
        参数：
        ----------
        global_model : nn.Module
            全局模型
            
        client_models : List[nn.Module]
            客户端模型列表
            
        其他参数同aggregate()
            
        返回：
        ----------
        aggregated_update : Dict[str, torch.Tensor]
            聚合后的全局更新
            
        trust_scores : np.ndarray
            信任分数数组
        """
        # 计算客户端更新（模型差）
        global_state = global_model.state_dict()
        client_updates = []
        
        for client_model in client_models:
            client_state = client_model.state_dict()
            update = {}
            for name in global_state.keys():
                if 'weight' in name or 'bias' in name:
                    update[name] = client_state[name] - global_state[name]
            client_updates.append(update)
        
        # 调用聚合
        return self.aggregate(
            global_model=global_model,
            client_updates=client_updates,
            criterion=criterion,
            learning_rate=learning_rate,
            batch_size=batch_size,
            num_steps=num_steps
        )


def create_root_dataset(full_dataset, 
                       num_samples: int = 100,
                       num_classes: int = 10,
                       sampling_mode: str = 'uniform') -> TensorDataset:
    """
    创建根数据集的辅助函数
    
    参数：
    ----------
    full_dataset : Dataset
        完整数据集
        
    num_samples : int
        根数据集大小
        
    num_classes : int
        类别数量
        
    sampling_mode : str
        采样模式:
        - 'uniform': 均匀采样
        - 'balanced': 类别平衡采样
        
    返回：
    ----------
    root_dataset : TensorDataset
        根数据集
    """
    if sampling_mode == 'uniform':
        # 均匀随机采样
        indices = np.random.choice(len(full_dataset), num_samples, replace=False)
        
    elif sampling_mode == 'balanced':
        # 类别平衡采样
        samples_per_class = num_samples // num_classes
        indices = []
        
        # 收集每个类别的索引
        class_indices = {i: [] for i in range(num_classes)}
        for idx in range(len(full_dataset)):
            _, label = full_dataset[idx]
            if isinstance(label, torch.Tensor):
                label = label.item()
            class_indices[label].append(idx)
        
        # 从每个类别采样
        for class_id in range(num_classes):
            if len(class_indices[class_id]) >= samples_per_class:
                sampled = np.random.choice(
                    class_indices[class_id],
                    samples_per_class,
                    replace=False
                )
                indices.extend(sampled)
    
    else:
        raise ValueError(f"未知的采样模式: {sampling_mode}")
    
    # 创建根数据集
    root_data = []
    root_labels = []
    for idx in indices:
        data, label = full_dataset[idx]
        root_data.append(data)
        root_labels.append(label)
    
    root_data = torch.stack(root_data)
    root_labels = torch.tensor(root_labels)
    
    root_dataset = TensorDataset(root_data, root_labels)
    
    print(f"[创建根数据集] 完成")
    print(f"  - 大小: {len(root_dataset)}")
    print(f"  - 采样模式: {sampling_mode}")
    
    return root_dataset
