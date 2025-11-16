#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TEE-FL vs FLTrust vs FedAvg 防御机制对比实验

对比三种聚合方法：
1. TEE-FL: 方向相似度检测器（师兄的方法）
2. FLTrust: 信任分数聚合（NeurIPS 2020）
3. FedAvg: 简单平均（无防御baseline）

实验场景：
- 攻击类型: PoisonedFL, Label Flipping, 无攻击
- 恶意客户端比例: 0%, 20%, 40%, 60%
- 数据集: MNIST (IID)

评估指标：
- 模型测试准确率
- 攻击检测率（仅TEE-FL）
- 训练时间
- 收敛曲线
"""

import sys
import os
import copy
import torch
import torch.nn as nn
import numpy as np
import json
import time
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

# 添加路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 导入TEE-FL组件
from utils.options import args_parser
from utils.get_dataset import get_dataset
from utils.sampling import mnist_iid, mnist_noniid
from models.lenet5 import LeNet5  # 修复：从lenet5模块导入
from models.standard_resnet18 import standard_resnet18  # ResNet18模型
from models.resnet20 import resnet20  # ResNet20模型
from models.Fed import Aggregation
from models import test as model_test

# 导入FLTrust防御
from defenses import FLTrust, create_root_dataset

# 导入攻击
from attacks.attack_manager import AttackManager

# 导入检测器
from independent_detectors_test import IndependentDetectorsTester

# cuDNN设置
torch.backends.cudnn.enabled = False
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'


class LocalUpdate:
    """本地训练类（支持FedProx用于Non-IID）"""
    def __init__(self, args, dataset, idxs):
        self.args = args
        self.device = torch.device(f'cuda:{args.gpu}' if torch.cuda.is_available() else 'cpu')
        self.ldr_train = torch.utils.data.DataLoader(
            torch.utils.data.Subset(dataset, list(idxs)),
            batch_size=self.args.local_bs,
            shuffle=True
        )
        self.criterion = nn.CrossEntropyLoss().to(self.device)
    
    def train(self, net, global_model=None):
        """本地训练（支持FedProx正则化用于Non-IID）
        
        Args:
            net: 本地模型
            global_model: 全局模型（用于FedProx约束）
        """
        net.train()
        optimizer = torch.optim.SGD(net.parameters(), lr=self.args.lr, momentum=0.9)
        
        # 保存全局模型参数（用于FedProx）
        global_params = None
        if global_model is not None and self.args.prox_alpha > 0:
            global_params = {name: param.clone().detach() for name, param in global_model.named_parameters()}
        
        epoch_loss = []
        for epoch in range(self.args.local_ep):
            batch_loss = []
            for batch_idx, (images, labels) in enumerate(self.ldr_train):
                images, labels = images.to(self.device), labels.to(self.device)
                
                net.zero_grad()
                log_probs = net(images)
                
                # 处理字典格式的输出（如LeNet5）
                if isinstance(log_probs, dict):
                    log_probs = log_probs['output']
                
                # 交叉熵损失
                loss = self.criterion(log_probs, labels)
                
                # FedProx正则化项（Non-IID必需）
                if global_params is not None:
                    proximal_term = 0.0
                    for name, param in net.named_parameters():
                        if name in global_params:
                            proximal_term += torch.sum((param - global_params[name]) ** 2)
                    loss += (self.args.prox_alpha / 2) * proximal_term
                
                loss.backward()
                optimizer.step()
                
                batch_loss.append(loss.item())
            epoch_loss.append(sum(batch_loss) / len(batch_loss))
        
        return net.state_dict(), sum(epoch_loss) / len(epoch_loss)
    
    def train_tee(self, tee_model, global_model=None, sample_ratio=0.3, num_epochs=20):
        """在客户端数据的子集上训练TEE模型（per-client TEE）
        
        这是TEE-FL的正确实现：每个客户端在自己的数据子集上训练TEE模型，
        确保TEE和客户端的数据分布一致（Non-IID环境下至关重要）。
        
        使用分层采样（stratified sampling）保持类别分布一致。
        
        Args:
            tee_model: TEE模型
            global_model: 全局模型（用于FedProx）
            sample_ratio: TEE数据采样比例（默认30%）
            num_epochs: 训练epoch数（默认20，与独立检测器测试一致）
        
        Returns:
            tee_model.state_dict(): 训练后的TEE模型参数
        """
        import random
        from collections import defaultdict
        
        tee_model.train()
        optimizer = torch.optim.SGD(tee_model.parameters(), lr=self.args.lr, momentum=0.9)
        
        # 保存全局模型参数（用于FedProx）
        global_params = None
        if global_model is not None and self.args.prox_alpha > 0:
            global_params = {name: param.clone().detach() for name, param in global_model.named_parameters()}
        
        # 分层采样TEE数据（按类别比例采样，与独立检测器测试一致）
        dataset = self.ldr_train.dataset.dataset  # 获取原始数据集
        client_indices = list(self.ldr_train.dataset.indices)  # 客户端的数据索引
        
        # 获取标签并按类别分组
        class_indices = defaultdict(list)
        for idx in client_indices:
            if hasattr(dataset, 'targets'):
                label = int(dataset.targets[idx])
            elif hasattr(dataset, 'labels'):
                label = int(dataset.labels[idx])
            else:
                _, label = dataset[idx]
                label = int(label)
            class_indices[label].append(idx)
        
        # 每类按比例采样
        tee_indices = []
        for label, indices in class_indices.items():
            n_samples = max(1, int(len(indices) * sample_ratio))
            sampled = random.sample(indices, n_samples)
            tee_indices.extend(sampled)
        
        # 直接从原始数据集创建Subset（tee_indices是原始数据集的全局索引）
        tee_dataset = torch.utils.data.Subset(dataset, tee_indices)
        tee_loader = torch.utils.data.DataLoader(
            tee_dataset,
            batch_size=self.args.local_bs,
            shuffle=True
        )
        
        # 训练num_epochs个epoch
        for epoch in range(num_epochs):
            for images, labels in tee_loader:
                images, labels = images.to(self.device), labels.to(self.device)
                
                tee_model.zero_grad()
                log_probs = tee_model(images)
                
                # 处理字典格式的输出
                if isinstance(log_probs, dict):
                    log_probs = log_probs['output']
                
                # 交叉熵损失
                loss = self.criterion(log_probs, labels)
                
                # FedProx正则化项
                if global_params is not None:
                    proximal_term = 0.0
                    for name, param in tee_model.named_parameters():
                        if name in global_params:
                            proximal_term += torch.sum((param - global_params[name]) ** 2)
                    loss += (self.args.prox_alpha / 2) * proximal_term
                
                loss.backward()
                optimizer.step()
        
        return tee_model.state_dict()


class DefenseComparison:
    """防御机制对比实验"""
    
    def __init__(self, args):
        """初始化对比实验"""
        self.args = args
        
        # 设置device（同时保存到args中，供IndependentDetectorsTester使用）
        self.device = torch.device(f'cuda:{args.gpu}' if torch.cuda.is_available() and args.gpu >= 0 else 'cpu')
        self.args.device = self.device  # 添加到args
        
        # 加载数据集
        print("\n" + "=" * 80)
        print("📦 加载数据集...")
        self.dataset_train, self.dataset_test, self.dict_users = get_dataset(args)
        
        # 创建根数据集（用于FLTrust）
        print("📦 创建FLTrust根数据集...")
        # 根据数据集大小自动计算根数据集大小（10%训练集）
        root_dataset_size = int(len(self.dataset_train) * 0.1)
        print(f"  根数据集大小: {root_dataset_size} (训练集的10%)")
        self.root_dataset = create_root_dataset(
            full_dataset=self.dataset_train,
            num_samples=root_dataset_size,  # MNIST: 6000, CIFAR-10: 5000
            num_classes=self.args.num_classes,  # 自动适配类别数
            sampling_mode='balanced'
        )
        
        # 注释：TEE-FL使用Per-client TEE，不需要全局验证集
        # 每个客户端在自己数据的30%子集上训练TEE模型（与独立检测器一致）
        
        # 初始化攻击管理器
        print("⚔️  初始化攻击管理器...")
        attack_config = {
            'attack_type': args.attack_type,
            'malicious_ratio': args.malicious_ratio,
            'attack_timing': 'all_rounds',  # 所有轮次都攻击
            'attack_params': {
                'args': args,
                'device': self.device,
                'attack_strength': 5.0,  # PoisonedFL攻击强度（强攻击场景）
                'consistency_weight': 0.5,
                'num_classes': 10,
            }
        }
        self.attack_manager = AttackManager(args.num_users, attack_config)
        
        # 创建测试数据加载器
        self.test_loader = torch.utils.data.DataLoader(
            self.dataset_test,
            batch_size=128,
            shuffle=False
        )
        
        # 实验结果存储
        self.results = {
            'fedavg_clean': {'accuracies': [], 'times': []},  # 新增：无攻击baseline
            'tee_fl': {'accuracies': [], 'times': [], 'detection_stats': []},
            'fltrust': {'accuracies': [], 'times': [], 'trust_scores': []},
            'fedavg': {'accuracies': [], 'times': []},
            'config': vars(args)
        }
        
        print("=" * 80)
        print("✅ 对比实验初始化完成")
        print("=" * 80)
        print(f"📊 数据集: {args.dataset}")
        print(f"📊 客户端数量: {args.num_users}")
        print(f"📊 恶意客户端比例: {args.malicious_ratio}")
        print(f"📊 攻击类型: {args.attack_type}")
        print(f"📊 训练轮数: {args.epochs}")
        print(f"📊 Warmup轮数: 3 (前3轮无攻击)")
        print(f"📊 数据分布: {'IID' if args.iid else f'Non-IID (case={args.noniid_case}, beta={args.data_beta})'}")
        if not args.iid:
            print(f"📊 FedProx正则化: μ={args.prox_alpha} (用于Non-IID收敛)")
        print(f"📊 FLTrust根数据集: {len(self.root_dataset)}样本")
        print(f"📊 TEE-FL方法: Per-client TEE (每个客户端用自己30%数据训练TEE)")
        print("=" * 80 + "\n")
    
    def _create_model(self):
        """创建新模型"""
        if self.args.model == 'lenet':
            return LeNet5().to(self.device)
        elif self.args.model == 'resnet':
            # 使用标准ResNet18（适用于CIFAR-10/100）
            return standard_resnet18(
                num_classes=self.args.num_classes,
                num_channels=self.args.num_channels,
                track_running_stats=False  # FL中通常不跟踪BN统计
            ).to(self.device)
        elif self.args.model == 'resnet20':
            # 使用ResNet20（更轻量级）
            return resnet20(
                num_classes=self.args.num_classes,
                num_channels=self.args.num_channels,
                track_running_stats=False
            ).to(self.device)
        else:
            raise NotImplementedError(f"模型 {self.args.model} 未实现，支持的模型: lenet, resnet, resnet20")
    
    def _test_model(self, model):
        """测试模型准确率"""
        model.eval()
        test_loss = 0
        correct = 0
        criterion = nn.CrossEntropyLoss()
        
        with torch.no_grad():
            for data, target in self.test_loader:
                data, target = data.to(self.device), target.to(self.device)
                output = model(data)
                
                # 处理字典格式的输出（如LeNet5）
                if isinstance(output, dict):
                    output = output['output']
                
                test_loss += criterion(output, target).item()
                pred = output.argmax(dim=1, keepdim=True)
                correct += pred.eq(target.view_as(pred)).sum().item()
        
        test_loss /= len(self.test_loader)
        accuracy = 100. * correct / len(self.test_loader.dataset)
        
        return accuracy, test_loss
    
    def _train_tee_model(self, global_model, num_epochs=20):
        """在TEE验证集上训练模型（用于检测）
        
        使用epoch-based训练，与独立检测器测试保持一致：
        tee_local_ep = int(local_ep / 0.3 * 0.6) = int(10 / 0.3 * 0.6) = 20 epochs
        
        Args:
            global_model: 当前全局模型
            num_epochs: 训练epoch数（默认20，与独立检测器测试一致）
            
        Returns:
            tee_model: 在TEE验证集上训练后的模型
        """
        # 复制全局模型
        tee_model = self._create_model()
        tee_model.load_state_dict(global_model.state_dict())
        tee_model.train()
        
        # 优化器和损失函数
        optimizer = torch.optim.SGD(tee_model.parameters(), lr=self.args.lr, momentum=0.9)
        criterion = nn.CrossEntropyLoss()
        
        # 训练num_epochs个epoch（完整遍历数据集）
        for epoch in range(num_epochs):
            for data, target in self.tee_validation_loader:
                data, target = data.to(self.device), target.to(self.device)
                
                optimizer.zero_grad()
                output = tee_model(data)
                
                # 处理字典格式的输出
                if isinstance(output, dict):
                    output = output['output']
                
                loss = criterion(output, target)
                loss.backward()
                optimizer.step()
        
        return tee_model
    
    def run_fedavg_clean(self):
        """运行FedAvg（无攻击baseline，展示正常性能上限）"""
        print("\n" + "=" * 80)
        print("🟦 Baseline: FedAvg (无攻击 - 性能上限)")
        print("=" * 80)
        
        start_time = time.time()
        global_model = self._create_model()
        criterion = nn.CrossEntropyLoss()
        
        # Warmup期设置
        warmup_epochs = 3
        
        # 训练循环（无攻击）
        for epoch in tqdm(range(self.args.epochs), desc="FedAvg无攻击训练"):
            local_weights = []
            m = max(int(self.args.frac * self.args.num_users), 1)
            idxs_users = np.random.choice(range(self.args.num_users), m, replace=False)
            
            for idx in idxs_users:
                # 本地训练（传入global_model用于FedProx）
                local = LocalUpdate(self.args, self.dataset_train, self.dict_users[idx])
                local_model = copy.deepcopy(global_model)
                w, loss = local.train(local_model, global_model)
                local_weights.append(copy.deepcopy(w))
            
            # 聚合（所有客户端都是良性的）
            local_lens = [len(self.dict_users[idx]) for idx in idxs_users]
            global_weights = Aggregation(local_weights, local_lens)
            global_model.load_state_dict(global_weights)
            
            # 测试
            if (epoch + 1) % self.args.test_freq == 0 or epoch == self.args.epochs - 1:
                acc, loss = self._test_model(global_model)
                self.results['fedavg_clean']['accuracies'].append({
                    'epoch': epoch + 1,
                    'accuracy': acc,
                    'loss': loss
                })
                print(f"\n[FedAvg-Clean] Epoch {epoch+1}: Acc = {acc:.2f}%, Loss = {loss:.4f}")
        
        # 记录总时间
        total_time = time.time() - start_time
        self.results['fedavg_clean']['times'].append(total_time)
        
        print(f"\n✅ FedAvg(无攻击)完成，总时间: {total_time:.2f}秒")
        print(f"📊 最终准确率: {self.results['fedavg_clean']['accuracies'][-1]['accuracy']:.2f}%")
        
        return global_model
    
    def run_fedavg(self):
        """运行FedAvg（有攻击，无防御）"""
        print("\n" + "=" * 80)
        print("🔵 方法1: FedAvg (有攻击 - 无防御)")
        print("=" * 80)
        
        # 创建全局模型
        global_model = self._create_model()
        global_model.train()
        
        # 记录起始时间
        start_time = time.time()
        
        # 训练循环
        for epoch in tqdm(range(self.args.epochs), desc="FedAvg训练"):
            local_weights = []
            m = max(int(self.args.frac * self.args.num_users), 1)
            idxs_users = np.random.choice(range(self.args.num_users), m, replace=False)
            
            # 设置本轮恶意客户端
            self.attack_manager.setup_malicious_clients(list(idxs_users), epoch, self.args.epochs)
            
            # 调试: 验证warmup机制
            if epoch < 4:  # 只在前4轮显示
                num_malicious = len(self.attack_manager.get_malicious_clients())
                print(f"\n[Warmup调试] Epoch {epoch+1}: 恶意客户端数量 = {num_malicious}/{len(idxs_users)}")
            
            for idx in idxs_users:
                # 本地训练（传入global_model用于FedProx）
                local = LocalUpdate(self.args, self.dataset_train, self.dict_users[idx])
                local_model = copy.deepcopy(global_model)
                w, loss = local.train(local_model, global_model)
                
                # 应用模型投毒攻击（PoisonedFL）
                if self.attack_manager.is_malicious(idx):
                    client_model = self._create_model()
                    client_model.load_state_dict(w)
                    poisoned_model = self.attack_manager.poison_model(
                        client_id=idx,
                        client_model=client_model,
                        global_model=global_model,
                        round_idx=epoch
                    )
                    w = poisoned_model.state_dict()
                
                local_weights.append(copy.deepcopy(w))
            
            # FedAvg聚合（加权平均，根据样本数量）
            lens = [len(self.dict_users[idx]) for idx in idxs_users]
            global_weights = Aggregation(local_weights, lens)
            global_model.load_state_dict(global_weights)
            
            # 测试
            if (epoch + 1) % self.args.test_freq == 0 or epoch == self.args.epochs - 1:
                acc, loss = self._test_model(global_model)
                self.results['fedavg']['accuracies'].append({
                    'epoch': epoch + 1,
                    'accuracy': acc,
                    'loss': loss
                })
                print(f"\n[FedAvg] Epoch {epoch+1}: Acc = {acc:.2f}%, Loss = {loss:.4f}")
        
        # 记录总时间
        total_time = time.time() - start_time
        self.results['fedavg']['times'].append(total_time)
        
        print(f"\n✅ FedAvg完成，总时间: {total_time:.2f}秒")
        print(f"📊 最终准确率: {self.results['fedavg']['accuracies'][-1]['accuracy']:.2f}%")
        
        return global_model
    
    def run_tee_fl(self):
        """运行TEE-FL（完整的方向相似度检测器）"""
        print("\n" + "=" * 80)
        print("🟢 方法2: TEE-FL (完整方向相似度检测器)")
        print("=" * 80)
        print("Per-client TEE: 每个客户端在自己30%数据上训练TEE模型")
        print("检测方法: 计算客户端更新与TEE更新的余弦相似度")
        print("=" * 80)
        
        # 创建全局模型
        global_model = self._create_model()
        global_model.train()
        
        # 初始化检测器
        detector = IndependentDetectorsTester(self.args)
        
        # 记录起始时间
        start_time = time.time()
        
        # 统计信息
        detection_stats = {
            'total_clients': 0,
            'detected_malicious': 0,
            'true_malicious': 0,
            'true_positives': 0,
            'false_positives': 0,
            'false_negatives': 0
        }
        
        # Warmup期设置（前几轮让模型收敛，不进行检测）
        warmup_epochs = 3
        
        # 训练循环
        for epoch in tqdm(range(self.args.epochs), desc="TEE-FL训练"):
            local_weights = []
            accepted_weights = []
            accepted_idx_list = []  # 记录通过检测的客户端ID
            m = max(int(self.args.frac * self.args.num_users), 1)
            idxs_users = np.random.choice(range(self.args.num_users), m, replace=False)
            
            # 设置本轮恶意客户端
            self.attack_manager.setup_malicious_clients(list(idxs_users), epoch, self.args.epochs)
            
            # Warmup期标识
            if epoch < warmup_epochs:
                print(f"\n  [Warmup模式] Epoch {epoch+1}/{warmup_epochs}: 跳过检测，直接聚合所有客户端")
            
            for idx in idxs_users:
                # 本地训练（传入global_model用于FedProx）
                local = LocalUpdate(self.args, self.dataset_train, self.dict_users[idx])
                local_model = copy.deepcopy(global_model)
                w, loss = local.train(local_model, global_model)
                
                # 训练该客户端的TEE模型（per-client TEE，使用客户端数据的30%子集）
                # 这是TEE-FL的正确实现：确保TEE和客户端的数据分布一致
                if epoch >= warmup_epochs:
                    # 只在检测期才需要训练TEE
                    tee_model = copy.deepcopy(global_model)
                    w_tee = local.train_tee(tee_model, global_model, sample_ratio=0.3, num_epochs=20)
                    tee_model.load_state_dict(w_tee)
                else:
                    tee_model = None  # Warmup期不需要TEE
                
                # 应用模型投毒攻击（PoisonedFL）
                is_malicious = self.attack_manager.is_malicious(idx)
                if is_malicious:
                    client_model = self._create_model()
                    client_model.load_state_dict(w)
                    poisoned_model = self.attack_manager.poison_model(
                        client_id=idx,
                        client_model=client_model,
                        global_model=global_model,
                        round_idx=epoch
                    )
                    w = poisoned_model.state_dict()
                
                local_weights.append(copy.deepcopy(w))
                
                # Warmup期（前3轮）跳过检测，让模型先收敛
                if epoch < warmup_epochs:
                    # Warmup期不检测，直接接受所有客户端
                    is_detected_malicious = False
                    detection_result = {}
                else:
                    # 正常检测：TEE-FL检测（完整版：使用方向相似度）
                    # 创建外部模型（客户端训练的模型）
                    external_model = self._create_model()
                    external_model.load_state_dict(w)
                    
                    # 使用完整的检测器测试
                    client_result = detector.test_update_direction_only(
                        global_model=global_model,
                        external_model=external_model,
                        tee_model=tee_model,
                        client_id=idx,
                        is_malicious=is_malicious,
                        validation_loader=None,  # Per-client TEE不需要全局验证集
                        attack_scenario=self.args.attack_type
                    )
                    
                    # 提取检测结果
                    detection_result = client_result['detectors'].get('update_direction', {}).get('detection_result', {})
                    
                    # 判断是否检测为恶意
                    is_detected_malicious = detection_result.get('is_anomaly', False)
                
                # 记录检测统计
                detection_stats['total_clients'] += 1
                if is_malicious:
                    detection_stats['true_malicious'] += 1
                
                # 调试输出
                if epoch < warmup_epochs:
                    # Warmup期输出
                    print(f"    [Warmup] 客户端{idx}: 跳过检测，直接接受")
                else:
                    # 攻击期输出所有检测详情
                    features = detection_result.get('features', {})
                    cos_sim = features.get('update_direction_similarity', 0.0)
                    print(f"    [检测] 客户端{idx}: 余弦相似度={cos_sim:.4f}, "
                          f"检测={'恶意' if is_detected_malicious else '良性'}, "
                          f"实际={'恶意' if is_malicious else '良性'}")
                
                if is_detected_malicious:
                    detection_stats['detected_malicious'] += 1
                    if is_malicious:
                        detection_stats['true_positives'] += 1
                    else:
                        detection_stats['false_positives'] += 1
                else:
                    if is_malicious:
                        detection_stats['false_negatives'] += 1
                    # 只接受检测为良性的客户端
                    accepted_weights.append(copy.deepcopy(w))
                    accepted_idx_list.append(idx)
            
            # 聚合（只聚合通过检测的客户端）
            if len(accepted_weights) > 0:
                # 计算通过检测的客户端的样本数量
                accepted_lens = [len(self.dict_users[idx]) for idx in accepted_idx_list]
                global_weights = Aggregation(accepted_weights, accepted_lens)
                global_model.load_state_dict(global_weights)
            else:
                print(f"⚠️ Epoch {epoch+1}: 所有客户端都被检测为恶意，保持全局模型不变")
            
            # 测试
            if (epoch + 1) % self.args.test_freq == 0 or epoch == self.args.epochs - 1:
                acc, loss = self._test_model(global_model)
                self.results['tee_fl']['accuracies'].append({
                    'epoch': epoch + 1,
                    'accuracy': acc,
                    'loss': loss
                })
                print(f"\n[TEE-FL] Epoch {epoch+1}: Acc = {acc:.2f}%, Loss = {loss:.4f}")
                print(f"  检测统计: {detection_stats['detected_malicious']}/{detection_stats['total_clients']} 被识别为恶意")
        
        # 记录总时间
        total_time = time.time() - start_time
        self.results['tee_fl']['times'].append(total_time)
        
        # 计算检测指标
        if detection_stats['true_malicious'] > 0:
            recall = detection_stats['true_positives'] / detection_stats['true_malicious']
        else:
            recall = 1.0
        
        if detection_stats['detected_malicious'] > 0:
            precision = detection_stats['true_positives'] / detection_stats['detected_malicious']
        else:
            precision = 1.0
        
        detection_stats['recall'] = recall
        detection_stats['precision'] = precision
        self.results['tee_fl']['detection_stats'].append(detection_stats)
        
        print(f"\n✅ TEE-FL完成，总时间: {total_time:.2f}秒")
        print(f"📊 最终准确率: {self.results['tee_fl']['accuracies'][-1]['accuracy']:.2f}%")
        print(f"🔍 检测召回率: {recall:.2%}")
        print(f"🔍 检测精确率: {precision:.2%}")
        
        return global_model
    
    def run_fltrust(self):
        """运行FLTrust（信任分数聚合）"""
        print("\n" + "=" * 80)
        print("🟡 方法3: FLTrust (信任分数聚合)")
        print("=" * 80)
        
        # 创建全局模型
        global_model = self._create_model()
        global_model.train()
        
        # 初始化FLTrust
        fltrust = FLTrust(
            root_dataset=self.root_dataset,
            device=self.device
        )
        
        criterion = nn.CrossEntropyLoss()
        
        # 记录起始时间
        start_time = time.time()
        
        # 训练循环
        for epoch in tqdm(range(self.args.epochs), desc="FLTrust训练"):
            client_models = []
            client_ids = []
            m = max(int(self.args.frac * self.args.num_users), 1)
            idxs_users = np.random.choice(range(self.args.num_users), m, replace=False)
            
            # 设置本轮恶意客户端
            self.attack_manager.setup_malicious_clients(list(idxs_users), epoch, self.args.epochs)
            
            for idx in idxs_users:
                # 本地训练（传入global_model用于FedProx）
                local = LocalUpdate(self.args, self.dataset_train, self.dict_users[idx])
                local_model = copy.deepcopy(global_model)
                w, loss = local.train(local_model, global_model)
                
                # 应用模型投毒攻击（PoisonedFL）
                if self.attack_manager.is_malicious(idx):
                    client_model = self._create_model()
                    client_model.load_state_dict(w)
                    poisoned_model = self.attack_manager.poison_model(
                        client_id=idx,
                        client_model=client_model,
                        global_model=global_model,
                        round_idx=epoch
                    )
                    w = poisoned_model.state_dict()
                
                # 创建客户端模型
                client_model = self._create_model()
                client_model.load_state_dict(w)
                client_models.append(client_model)
                client_ids.append(idx)
            
            # FLTrust聚合
            # 论文："the server computes one gradient step on the root dataset"
            # "one step"应理解为：在根数据集上完整训练1轮（1 epoch）
            # 6000样本，batch=32，需要约187步才能遍历完整数据集
            num_steps = len(self.root_dataset) // 32  # 1 epoch ≈ 187 steps
            print(f"[调试] FLTrust训练步数: {num_steps}步（根数据集{len(self.root_dataset)}样本）")
            
            aggregated_update, trust_scores = fltrust.aggregate_models(
                global_model=global_model,
                client_models=client_models,
                criterion=criterion,
                learning_rate=self.args.lr,
                batch_size=32,
                num_steps=num_steps  # 传递训练步数
            )
            
            # 记录信任分数
            self.results['fltrust']['trust_scores'].append({
                'epoch': epoch + 1,
                'scores': trust_scores.tolist(),
                'client_ids': client_ids,
                'mean': float(np.mean(trust_scores)),
                'std': float(np.std(trust_scores)),
                'min': float(np.min(trust_scores)),
                'max': float(np.max(trust_scores))
            })
            
            # 更新全局模型
            with torch.no_grad():
                for name, param in global_model.named_parameters():
                    if name in aggregated_update:
                        param.data += aggregated_update[name]
            
            # 测试
            if (epoch + 1) % self.args.test_freq == 0 or epoch == self.args.epochs - 1:
                acc, loss = self._test_model(global_model)
                self.results['fltrust']['accuracies'].append({
                    'epoch': epoch + 1,
                    'accuracy': acc,
                    'loss': loss
                })
                print(f"\n[FLTrust] Epoch {epoch+1}: Acc = {acc:.2f}%, Loss = {loss:.4f}")
                print(f"  信任分数: 平均={np.mean(trust_scores):.4f}, 最小={np.min(trust_scores):.4f}, 最大={np.max(trust_scores):.4f}")
        
        # 记录总时间
        total_time = time.time() - start_time
        self.results['fltrust']['times'].append(total_time)
        
        print(f"\n✅ FLTrust完成，总时间: {total_time:.2f}秒")
        print(f"📊 最终准确率: {self.results['fltrust']['accuracies'][-1]['accuracy']:.2f}%")
        
        return global_model
    
    def run_all(self):
        """运行所有对比实验"""
        print("\n" + "🚀 " + "=" * 76 + " 🚀")
        print("开始对比实验: TEE-FL vs FLTrust vs FedAvg (有攻击) vs FedAvg (无攻击)")
        print("🚀 " + "=" * 76 + " 🚀\n")
        
        # 运行四种方法（先运行baseline展示正常性能）
        self.run_fedavg_clean()  # 新增：无攻击baseline
        self.run_fedavg()        # 有攻击，无防御
        self.run_tee_fl()        # 有攻击，TEE-FL防御
        self.run_fltrust()       # 有攻击，FLTrust防御
        
        # 生成对比报告
        self.generate_report()
        
        # 保存结果
        self.save_results()
    
    def generate_report(self):
        """生成对比报告"""
        print("\n" + "=" * 80)
        print("📊 对比实验报告")
        print("=" * 80)
        
        # 检查哪些方法有结果
        has_fedavg_clean = len(self.results['fedavg_clean']['accuracies']) > 0
        has_fedavg = len(self.results['fedavg']['accuracies']) > 0
        has_teefl = len(self.results['tee_fl']['accuracies']) > 0
        has_fltrust = len(self.results['fltrust']['accuracies']) > 0
        
        # 最终准确率对比
        print("\n🎯 最终准确率对比:")
        print("-" * 80)
        
        # Baseline: 无攻击的FedAvg
        if has_fedavg_clean:
            clean_acc = self.results['fedavg_clean']['accuracies'][-1]['accuracy']
            print(f"  🟦 FedAvg (无攻击-Baseline): {clean_acc:6.2f}%  ← 性能上限")
            print()
        
        # 有攻击的方法对比
        if has_fedavg:
            fedavg_acc = self.results['fedavg']['accuracies'][-1]['accuracy']
            if has_fedavg_clean:
                drop = clean_acc - fedavg_acc
                print(f"  🔵 FedAvg (有攻击-无防御): {fedavg_acc:6.2f}%  (下降 {drop:.2f}%)")
            else:
                print(f"  🔵 FedAvg (有攻击-无防御): {fedavg_acc:6.2f}%")
        
        if has_teefl:
            teefl_acc = self.results['tee_fl']['accuracies'][-1]['accuracy']
            if has_fedavg_clean:
                drop = clean_acc - teefl_acc
                print(f"  🟢 TEE-FL (有攻击+防御):   {teefl_acc:6.2f}%  (下降 {drop:.2f}%)")
            else:
                print(f"  🟢 TEE-FL (有攻击+防御):   {teefl_acc:6.2f}%")
        
        if has_fltrust:
            fltrust_acc = self.results['fltrust']['accuracies'][-1]['accuracy']
            if has_fedavg_clean:
                drop = clean_acc - fltrust_acc
                print(f"  🟡 FLTrust (有攻击+防御):  {fltrust_acc:6.2f}%  (下降 {drop:.2f}%)")
            else:
                print(f"  🟡 FLTrust (有攻击+防御):  {fltrust_acc:6.2f}%")
        
        # 训练时间对比
        if has_fedavg or has_teefl or has_fltrust:
            print("\n⏱️  训练时间对比:")
            print("-" * 80)
            
            if has_fedavg:
                fedavg_time = self.results['fedavg']['times'][0]
                print(f"  FedAvg:  {fedavg_time:7.2f}秒")
            
            if has_teefl:
                teefl_time = self.results['tee_fl']['times'][0]
                if has_fedavg:
                    print(f"  TEE-FL:  {teefl_time:7.2f}秒 ({teefl_time/fedavg_time:.2f}x)")
                else:
                    print(f"  TEE-FL:  {teefl_time:7.2f}秒")
            
            if has_fltrust:
                fltrust_time = self.results['fltrust']['times'][0]
                if has_fedavg:
                    print(f"  FLTrust: {fltrust_time:7.2f}秒 ({fltrust_time/fedavg_time:.2f}x)")
                else:
                    print(f"  FLTrust: {fltrust_time:7.2f}秒")
        
        # TEE-FL检测统计
        if len(self.results['tee_fl']['detection_stats']) > 0:
            stats = self.results['tee_fl']['detection_stats'][0]
            print("\n🔍 TEE-FL检测统计:")
            print("-" * 80)
            print(f"  召回率 (Recall):    {stats['recall']:.2%}")
            print(f"  精确率 (Precision):  {stats['precision']:.2%}")
            print(f"  真阳性 (TP):        {stats['true_positives']}")
            print(f"  假阳性 (FP):        {stats['false_positives']}")
            print(f"  假阴性 (FN):        {stats['false_negatives']}")
        
        # FLTrust信任分数统计
        if len(self.results['fltrust']['trust_scores']) > 0:
            print("\n📊 FLTrust信任分数统计 (最后一轮):")
            print("-" * 80)
            last_scores = self.results['fltrust']['trust_scores'][-1]
            print(f"  平均值: {last_scores['mean']:.4f}")
            print(f"  标准差: {last_scores['std']:.4f}")
            print(f"  最小值: {last_scores['min']:.4f}")
            print(f"  最大值: {last_scores['max']:.4f}")
        
        print("\n" + "=" * 80)
    
    def save_results(self):
        """保存实验结果"""
        # 创建结果目录
        results_dir = Path("results/defense_comparison")
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"comparison_{self.args.attack_type}_mr{int(self.args.malicious_ratio*100)}_{timestamp}.json"
        filepath = results_dir / filename
        
        # 转换numpy类型为Python原生类型
        def convert_to_serializable(obj):
            """递归转换numpy类型为Python原生类型"""
            if isinstance(obj, dict):
                return {key: convert_to_serializable(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [convert_to_serializable(item) for item in obj]
            elif isinstance(obj, torch.device):
                return str(obj)
            elif isinstance(obj, (np.integer, np.int32, np.int64)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float32, np.float64)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            else:
                return obj
        
        # 保存结果
        serializable_results = convert_to_serializable(self.results)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(serializable_results, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 实验结果已保存到: {filepath}")


def main():
    """主函数"""
    # 解析参数
    args = args_parser()
    
    # 创建对比实验
    comparison = DefenseComparison(args)
    
    # 运行所有对比实验
    comparison.run_all()


if __name__ == '__main__':
    main()
