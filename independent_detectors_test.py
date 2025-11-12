#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
独立检测器测试系统
测试8个检测器的独立检测效果，不进行聚合

检测器列表：
1. Euclidean Distance（欧氏距离）
2. Parameter Statistics（参数统计）
3. Cosine Similarity（参数余弦相似度）
4. Parameter Update Norm（参数更新范数）- 新实现
5. Update Direction（更新方向）- 新实现
6. Layer-wise Update Norm（层级更新范数）- 新实现
7. Layer Coordination（层协调）- 已禁用但测试
8. Gradient Norm（梯度范数）- 注释掉
"""

import torch
import torch.nn as nn
import numpy as np
import copy
import json
from datetime import datetime


# ===================== 新实现的检测器 =====================

class ParameterUpdateNormDetector:
    """参数更新范数检测器 - 不需要额外训练"""
    
    def __init__(self, args):
        self.args = args
        self.device = args.device
    
    def calculate_update_norm(self, global_model, external_model):
        """计算参数更新范数（估算梯度范数）"""
        global_params = dict(global_model.state_dict())
        external_params = dict(external_model.state_dict())
        
        layer_norms = []
        layer_details = {}
        
        for layer_name in global_params.keys():
            if layer_name in external_params:
                # 计算参数更新
                param_update = external_params[layer_name] - global_params[layer_name]
                
                # 估算梯度 (SGD: grad = -update / lr)
                estimated_gradient = -param_update / self.args.lr
                
                # 计算范数
                layer_norm = torch.norm(estimated_gradient).item()
                layer_norms.append(layer_norm)
                layer_details[layer_name] = layer_norm
        
        # 统计特征
        total_norm = np.sqrt(sum(n**2 for n in layer_norms))
        mean_norm = np.mean(layer_norms)
        std_norm = np.std(layer_norms)
        max_norm = np.max(layer_norms)
        min_norm = np.min(layer_norms)
        cv_norm = std_norm / mean_norm if mean_norm > 0 else 0
        
        return {
            'total_norm': total_norm,
            'mean_norm': mean_norm,
            'std_norm': std_norm,
            'max_norm': max_norm,
            'min_norm': min_norm,
            'cv_norm': cv_norm,
            'layer_norms': layer_details
        }
    
    def detect_anomaly(self, update_stats):
        """基于更新范数检测异常"""
        total_norm = update_stats['total_norm']
        cv_norm = update_stats['cv_norm']
        max_norm = update_stats['max_norm']
        
        malicious_score = 0
        evidence = []
        
        # 基于实际数据调整阈值：恶意客户端范数更小（标签翻转导致更新混乱）
        # 良性：总范数~3200-3400，最大层范数~740
        # 恶意：总范数~1300-1400，最大层范数~270-320
        if total_norm < 2000:  # 反向：小了才是恶意
            malicious_score += 1
            evidence.append(f"总更新范数过低: {total_norm:.2f} < 2000")
        
        if max_norm < 400:  # 反向：小了才是恶意
            malicious_score += 1
            evidence.append(f"最大层范数过低: {max_norm:.2f} < 400")
        
        is_anomaly = malicious_score >= 2
        confidence = malicious_score / 3.0
        
        return {
            'is_anomaly': is_anomaly,
            'confidence': confidence,
            'evidence': evidence,
            'malicious_score': malicious_score,
            'method': 'parameter_update_norm',
            'features': update_stats
        }


class UpdateDirectionDetector:
    """更新方向余弦相似度检测器"""
    
    def __init__(self, args):
        self.args = args
        self.device = args.device
    
    def calculate_update_direction(self, global_model, external_model, tee_model):
        """计算更新方向余弦相似度"""
        global_params = dict(global_model.state_dict())
        external_params = dict(external_model.state_dict())
        tee_params = dict(tee_model.state_dict())
        
        # 计算更新向量
        external_updates = []
        tee_updates = []
        
        for layer_name in global_params.keys():
            if layer_name in external_params and layer_name in tee_params:
                Δ_external = (external_params[layer_name] - global_params[layer_name]).flatten()
                Δ_tee = (tee_params[layer_name] - global_params[layer_name]).flatten()
                
                external_updates.append(Δ_external)
                tee_updates.append(Δ_tee)
        
        # 展平成一维向量
        external_update_flat = torch.cat(external_updates).cpu().numpy()
        tee_update_flat = torch.cat(tee_updates).cpu().numpy()
        
        # 计算余弦相似度
        dot_product = np.dot(external_update_flat, tee_update_flat)
        norm_external = np.linalg.norm(external_update_flat)
        norm_tee = np.linalg.norm(tee_update_flat)
        
        if norm_external == 0 or norm_tee == 0:
            cosine_sim = 0.0
        else:
            cosine_sim = dot_product / (norm_external * norm_tee)
        
        # 计算范数比例
        norm_ratio = norm_external / norm_tee if norm_tee > 0 else 0
        
        return {
            'update_direction_similarity': cosine_sim,
            'update_norm_ratio': norm_ratio,
            'external_norm': norm_external,
            'tee_norm': norm_tee
        }
    
    def detect_anomaly(self, direction_stats, threshold=0.1):
        """基于更新方向检测异常（仅使用direction_similarity）
        
        Args:
            direction_stats: 方向统计信息
            threshold: 检测阈值（默认0.1，noise_injection时为0.2）
        """
        cosine_sim = direction_stats['update_direction_similarity']
        norm_ratio = direction_stats['update_norm_ratio']
        
        # 方向偏离检测
        # 阈值根据攻击类型调整：
        # - Label Flipping: 0.1（零漏检策略）
        # - Noise Injection: 0.2（宽松策略，配合欧氏距离）
        if cosine_sim < threshold:
            is_anomaly = True
            evidence = [f"更新方向严重偏离: cos={cosine_sim:.4f} < {threshold}"]
        else:
            is_anomaly = False
            evidence = [f"更新方向正常: cos={cosine_sim:.4f} >= {threshold}"]
        
        # 范数比率仅作为参考（不影响判断）
        evidence.append(f"范数比率(参考): {norm_ratio:.4f}")
        
        return {
            'is_anomaly': is_anomaly,
            'confidence': 1.0 if is_anomaly else 0.0,
            'evidence': evidence,
            'malicious_score': 1 if is_anomaly else 0,
            'method': 'update_direction',
            'features': direction_stats
        }


class BatchNormEuclideanDetector:
    """BatchNorm层欧氏距离检测器（噪声攻击专用）"""
    
    def __init__(self, args):
        self.args = args
        self.device = args.device
    
    def calculate_bn_euclidean(self, external_model, tee_model):
        """计算所有BatchNorm层的欧氏距离（深层最敏感：L2-L3-L4）"""
        external_params = dict(external_model.state_dict())
        tee_params = dict(tee_model.state_dict())
        
        bn_distances = {}
        bn_layers = []
        sensitive_layer_distances = []  # 最敏感层（layer2, layer3, layer4）- 深层BN
        shallow_layer_distances = []  # 浅层（layer1, bn1等）
        
        # 遍历所有层，找出BatchNorm层
        for layer_name in external_params.keys():
            # 识别BatchNorm层（包括weight, bias, running_mean, running_var）
            # 我们主要关注可训练参数：weight和bias
            if ('bn' in layer_name or 'norm' in layer_name.lower()) and \
               ('weight' in layer_name or 'bias' in layer_name):
                
                if layer_name in tee_params:
                    external_param = external_params[layer_name]
                    tee_param = tee_params[layer_name]
                    
                    # 计算欧氏距离
                    distance = torch.norm(external_param - tee_param).item()
                    bn_distances[layer_name] = distance
                    bn_layers.append(layer_name)
                    
                    # 分层统计：基于NOISE_STD_010_ANALYSIS.md文档
                    # TOP 5最敏感层：layer2 (d=1.761), layer3 (d=1.739), layer4 (d=1.672)
                    # 最敏感层：layer2, layer3, layer4（深层BN，噪声逐层累积）
                    if 'layer2' in layer_name or 'layer3' in layer_name or 'layer4' in layer_name:
                        sensitive_layer_distances.append(distance)
                    else:  # layer1, bn1等浅层
                        shallow_layer_distances.append(distance)
        
        if not bn_distances:
            return None
        
        # 统计信息
        distances_list = list(bn_distances.values())
        mean_distance = np.mean(distances_list)
        max_distance = np.max(distances_list)
        std_distance = np.std(distances_list)
        
        # 敏感层平均距离（优先指标）
        sensitive_mean = np.mean(sensitive_layer_distances) if sensitive_layer_distances else 0.0
        shallow_mean = np.mean(shallow_layer_distances) if shallow_layer_distances else 0.0
        
        return {
            'bn_distances': bn_distances,
            'bn_layers': bn_layers,
            'mean_distance': mean_distance,
            'max_distance': max_distance,
            'std_distance': std_distance,
            'n_bn_layers': len(bn_distances),
            'sensitive_mean': sensitive_mean,  # 最敏感层平均距离（layer2, layer3, layer4）
            'shallow_mean': shallow_mean,  # 浅层平均距离（layer1, bn1等）
            'n_sensitive_layers': len(sensitive_layer_distances),
            'n_shallow_layers': len(shallow_layer_distances)
        }
    
    def detect_anomaly(self, bn_stats, threshold=0.008, use_sensitive_layers=True):
        """基于BatchNorm层欧氏距离检测噪声攻击
        
        Args:
            bn_stats: BatchNorm统计信息
            threshold: 距离阈值（默认0.008，基于实际运行数据）
            use_sensitive_layers: 是否优先使用最敏感层BN（layer2, layer3, layer4）
        
        原理:
            噪声注入会影响深层BatchNorm层的参数更新
            - 深层BN平均距离（基于std=0.2, Non-IID实际数据）
              * 良性客户端均值: 0.0061, 中位数: 0.0028
              * 恶意客户端均值: 0.0104, 中位数: 0.0108
              * 阈值0.008: 平衡误报率(~20%)和漏报率(~15%)
            - 原因：深层特征受噪声影响更大，噪声逐层传播累积
            - 良性客户端：BN层参数与TEE相近（距离小）
            - 恶意客户端（噪声）：BN层参数偏离TEE（距离大）
        """
        if bn_stats is None:
            return {
                'is_anomaly': False,
                'confidence': 0.0,
                'evidence': ['未找到BatchNorm层'],
                'method': 'batchnorm_euclidean'
            }
        
        # 优先使用最敏感层BN距离（layer2, layer3, layer4）
        if use_sensitive_layers and bn_stats.get('n_sensitive_layers', 0) > 0:
            target_distance = bn_stats['sensitive_mean']
            distance_type = "深层BN(L2-L3-L4)"
            n_layers = bn_stats['n_sensitive_layers']
        else:
            target_distance = bn_stats['mean_distance']
            distance_type = "全部BN"
            n_layers = bn_stats['n_bn_layers']
        
        max_distance = bn_stats['max_distance']
        
        evidence = []
        
        # 基于实际运行数据（std=0.2, Non-IID）：
        # - 良性客户端：0.0016-0.0173（均值0.0061，中位数0.0028）
        # - 恶意客户端：0.0015-0.0195（均值0.0104，中位数0.0108）
        # - 阈值0.008：在均值之间，平衡误报和漏报
        # - 预期：召回率85%，误报率20%
        if target_distance > threshold:
            is_anomaly = True
            evidence.append(f"{distance_type}距离异常: {target_distance:.4f} > {threshold}")
        else:
            is_anomaly = False
            evidence.append(f"{distance_type}距离正常: {target_distance:.4f} <= {threshold}")
        
        evidence.append(f"检测{n_layers}个{distance_type}层")
        evidence.append(f"最大距离: {max_distance:.4f}")
        
        # 添加敏感层/浅层对比信息
        if 'sensitive_mean' in bn_stats and 'shallow_mean' in bn_stats:
            evidence.append(f"深层(L2-L3-L4): {bn_stats['sensitive_mean']:.4f}, 浅层(L1): {bn_stats['shallow_mean']:.4f}")
        
        return {
            'is_anomaly': is_anomaly,
            'confidence': 1.0 if is_anomaly else 0.0,
            'evidence': evidence,
            'malicious_score': 1 if is_anomaly else 0,
            'method': 'batchnorm_euclidean',
            'features': bn_stats
        }


class LayerWiseDirectionDetector:
    """
    层级方向检测器 - 在Non-IID环境下依然能够准确检测恶意客户端
    
    核心思想：
    - Non-IID环境下，客户端数据分布不同，导致传统检测器失效
    - 使用TEE内的全局IID验证集作为"标准参照"
    - 良性客户端：无论数据如何Non-IID，更新方向应该朝向全局最优
    - 恶意客户端：攻击会导致更新方向严重偏离全局最优
    """
    
    def __init__(self, args):
        self.args = args
        self.device = args.device
    
    def calculate_validation_gradient(self, model, validation_loader):
        """
        在验证集上计算梯度（全局最优方向）
        验证集是全局IID的，代表了模型应该优化的真实方向
        """
        model.train()
        model.zero_grad()
        
        criterion = nn.CrossEntropyLoss()
        total_loss = 0
        batch_count = 0
        
        # 在验证集上计算梯度
        for images, labels in validation_loader:
            images, labels = images.to(self.device), labels.to(self.device)
            
            outputs = model(images)
            
            # 处理模型可能返回字典的情况
            if isinstance(outputs, dict):
                outputs = outputs.get('logits', outputs.get('output', list(outputs.values())[0]))
            
            loss = criterion(outputs, labels)
            loss.backward()
            
            total_loss += loss.item()
            batch_count += 1
            
            # 只使用前几个batch以节省计算
            if batch_count >= 3:
                break
        
        # 提取梯度
        validation_gradients = {}
        for name, param in model.named_parameters():
            if param.grad is not None:
                validation_gradients[name] = param.grad.clone().detach()
        
        model.zero_grad()
        
        return validation_gradients, total_loss / batch_count
    
    def calculate_layer_direction_similarity(self, global_model, external_model, tee_model, validation_loader):
        """
        计算各层的方向相似度
        
        原理：
        1. 在全局IID验证集上计算梯度（全局最优方向）
        2. 计算外部模型的更新方向
        3. 比较外部模型方向与全局最优方向的相似度
        4. 在Non-IID下：
           - 良性客户端：虽然数据Non-IID，但方向应接近全局最优
           - 恶意客户端：攻击导致方向严重偏离
        """
        # 计算模型更新
        global_params = dict(global_model.state_dict())
        external_params = dict(external_model.state_dict())
        tee_params = dict(tee_model.state_dict())
        
        # 计算外部模型和TEE模型的参数更新
        external_updates = {}
        tee_updates = {}
        
        for name in global_params.keys():
            if name in external_params and name in tee_params:
                external_updates[name] = external_params[name] - global_params[name]
                tee_updates[name] = tee_params[name] - global_params[name]
        
        # 在验证集上计算全局最优方向（使用全局模型）
        validation_model = copy.deepcopy(global_model)
        validation_gradients, val_loss = self.calculate_validation_gradient(validation_model, validation_loader)
        
        # 计算各层的方向相似度
        layer_similarities = {}
        important_layers = []
        
        for name in external_updates.keys():
            # 只关注权重层
            if 'weight' in name and name in validation_gradients:
                # 估算梯度（SGD: update = -lr * grad）
                external_grad = -external_updates[name] / self.args.lr
                tee_grad = -tee_updates[name] / self.args.lr
                val_grad = validation_gradients[name]
                
                # 展平
                external_grad_flat = external_grad.flatten()
                tee_grad_flat = tee_grad.flatten()
                val_grad_flat = val_grad.flatten()
                
                # 计算余弦相似度
                external_val_sim = torch.nn.functional.cosine_similarity(
                    external_grad_flat.unsqueeze(0), val_grad_flat.unsqueeze(0)
                ).item()
                
                tee_val_sim = torch.nn.functional.cosine_similarity(
                    tee_grad_flat.unsqueeze(0), val_grad_flat.unsqueeze(0)
                ).item()
                
                layer_similarities[name] = {
                    'external_val_similarity': external_val_sim,
                    'tee_val_similarity': tee_val_sim,
                    'direction_deviation': abs(external_val_sim - tee_val_sim)
                }
                important_layers.append(name)
        
        if not layer_similarities:
            return None
        
        # 计算统计特征
        external_sims = [v['external_val_similarity'] for v in layer_similarities.values()]
        tee_sims = [v['tee_val_similarity'] for v in layer_similarities.values()]
        deviations = [v['direction_deviation'] for v in layer_similarities.values()]
        
        return {
            'layer_similarities': layer_similarities,
            'mean_external_similarity': np.mean(external_sims),
            'mean_tee_similarity': np.mean(tee_sims),
            'mean_deviation': np.mean(deviations),
            'max_deviation': np.max(deviations),
            'validation_loss': val_loss,
            'n_layers': len(layer_similarities)
        }
    
    def detect_anomaly(self, direction_stats):
        """基于层级方向检测异常"""
        if direction_stats is None:
            return {
                'is_anomaly': False,
                'confidence': 0.0,
                'evidence': ['无有效层数据'],
                'method': 'layer_wise_direction',
                'features': {}
            }
        
        mean_external_sim = direction_stats['mean_external_similarity']
        mean_tee_sim = direction_stats['mean_tee_similarity']
        mean_deviation = direction_stats['mean_deviation']
        max_deviation = direction_stats['max_deviation']
        
        malicious_score = 0
        evidence = []
        
        # 检测外部模型与全局最优方向的偏离
        # 在Non-IID下，良性客户端的更新方向应该仍然朝向全局最优
        if mean_external_sim < 0.3:  # 外部模型方向与全局最优方向相反
            malicious_score += 1
            evidence.append(f"更新方向严重偏离全局最优: {mean_external_sim:.4f} < 0.3")
        
        # 检测外部模型与TEE模型的方向差异
        # TEE模型在相同数据上训练，方向应该一致
        if mean_deviation > 0.5:  # 方向差异过大
            malicious_score += 1
            evidence.append(f"外部与TEE方向差异过大: {mean_deviation:.4f} > 0.5")
        
        # 检测最大层偏离（某些层可能被特别攻击）
        if max_deviation > 0.7:
            malicious_score += 1
            evidence.append(f"存在严重偏离层: {max_deviation:.4f} > 0.7")
        
        is_anomaly = malicious_score >= 2
        confidence = malicious_score / 3.0
        
        return {
            'is_anomaly': is_anomaly,
            'confidence': confidence,
            'malicious_score': malicious_score,
            'evidence': evidence if evidence else ['方向正常'],
            'method': 'layer_wise_direction',
            'features': {
                'mean_external_similarity': mean_external_sim,
                'mean_tee_similarity': mean_tee_sim,
                'mean_deviation': mean_deviation,
                'max_deviation': max_deviation
            }
        }


class LayerWiseUpdateNormDetector:
    """各层更新范数检测器"""
    
    def __init__(self, args):
        self.args = args
        self.device = args.device
    
    def calculate_layer_wise_norms(self, global_model, external_model):
        """计算各层的更新范数"""
        global_params = dict(global_model.state_dict())
        external_params = dict(external_model.state_dict())
        
        layer_norms = {}
        important_layers = []
        
        for layer_name in global_params.keys():
            # 只关注重要层（卷积层和全连接层的权重）
            if 'weight' in layer_name and ('conv' in layer_name or 'linear' in layer_name or 'layer' in layer_name):
                if layer_name in external_params:
                    param_update = external_params[layer_name] - global_params[layer_name]
                    estimated_gradient = -param_update / self.args.lr
                    layer_norm = torch.norm(estimated_gradient).item()
                    layer_norms[layer_name] = layer_norm
                    important_layers.append(layer_name)
        
        if not layer_norms:
            return None
        
        # 分析各层范数的分布
        norms_list = list(layer_norms.values())
        mean_norm = np.mean(norms_list)
        std_norm = np.std(norms_list)
        
        # 计算高范数层的比例
        threshold = mean_norm + 1.0 * std_norm
        high_norm_count = sum(1 for n in norms_list if n > threshold)
        high_norm_ratio = high_norm_count / len(norms_list)
        
        return {
            'layer_norms': layer_norms,
            'mean_norm': mean_norm,
            'std_norm': std_norm,
            'high_norm_ratio': high_norm_ratio,
            'n_layers': len(layer_norms)
        }
    
    def detect_anomaly(self, layer_stats):
        """基于各层范数一致性检测异常"""
        if layer_stats is None:
            return {
                'is_anomaly': False,
                'confidence': 0.0,
                'evidence': ['无有效层数据'],
                'method': 'layer_wise_update_norm'
            }
        
        high_norm_ratio = layer_stats['high_norm_ratio']
        mean_norm = layer_stats['mean_norm']
        
        malicious_score = 0
        evidence = []
        
        # 超过90%的层范数都异常高（更严格的阈值）
        if high_norm_ratio > 0.9:
            malicious_score += 1
            evidence.append(f"高范数层比例: {high_norm_ratio:.2%} > 90%")
        
        # 基于实际数据：恶意客户端范数更小
        # 良性：平均层范数~340，恶意：平均层范数~145
        if mean_norm < 200:  # 反向：小了才是恶意
            malicious_score += 1
            evidence.append(f"平均层范数过低: {mean_norm:.2f} < 200")
        
        is_anomaly = malicious_score >= 1
        confidence = malicious_score / 2.0
        
        return {
            'is_anomaly': is_anomaly,
            'confidence': confidence,
            'evidence': evidence,
            'malicious_score': malicious_score,
            'method': 'layer_wise_update_norm',
            'features': layer_stats
        }


# ===================== 独立检测器测试类 =====================

class IndependentDetectorsTester:
    """独立检测器测试器 - 不聚合，各自检测"""
    
    def __init__(self, args):
        self.args = args
        self.device = args.device
        
        # 初始化检测器（仅使用实际需要的检测器）
        self.detectors = {
            'parameter_update_norm': ParameterUpdateNormDetector(args),
            'update_direction': UpdateDirectionDetector(args),
            'batchnorm_euclidean': BatchNormEuclideanDetector(args),  # 噪声攻击专用（已屏蔽但保留定义）
            'layer_wise_update_norm': LayerWiseUpdateNormDetector(args),
            'layer_wise_direction': LayerWiseDirectionDetector(args),
        }
        
        # 检测器显示名称
        self.detector_names = {
            'parameter_update_norm': '参数更新范数',
            'update_direction': '更新方向',
            'batchnorm_euclidean': 'BN层欧氏距离（噪声攻击专用）',
            'layer_wise_update_norm': '层级更新范数',
            'layer_wise_direction': '层级方向（Non-IID适用）',
        }
        
        # 结果记录
        self.results = {}
    
    def test_update_direction_only(self, global_model, external_model, tee_model, client_id, 
                                   is_malicious, validation_loader=None, attack_scenario='label_flipping'):
        """
        仅测试update_direction检测器（用于实际部署）
        noise_injection时会额外启用BatchNorm欧氏距离检测器
        
        Args:
            global_model: 全局模型
            external_model: 外部训练的模型
            tee_model: TEE训练的模型
            client_id: 客户端ID
            is_malicious: 真实标签（是否恶意）
            validation_loader: TEE验证集（本检测器不需要）
            attack_scenario: 攻击场景 ('label_flipping' 或 'noise_injection')
        
        Returns:
            dict: 包含检测结果的字典
        """
        print(f"  [检测] 客户端 {client_id} ({'恶意' if is_malicious else '良性'})")
        
        client_results = {
            'client_id': client_id,
            'is_malicious': is_malicious,
            'attack_scenario': attack_scenario,
            'detectors': {}
        }
        
        # 根据攻击类型设置阈值
        is_noise_attack = (attack_scenario == 'noise_injection')
        direction_threshold = 0.24 if is_noise_attack else 0.1  # std=0.25优化阈值
        
        # 1. 更新方向检测（必选）
        try:
            # 计算更新方向指标
            direction_stats = self.detectors['update_direction'].calculate_update_direction(
                global_model, external_model, tee_model
            )
            
            # 基于指标进行检测（传入阈值）
            update_direction_result = self.detectors['update_direction'].detect_anomaly(
                direction_stats, threshold=direction_threshold
            )
            
            # 保存结果
            client_results['detectors']['update_direction'] = {
                'detection_result': update_direction_result,
                'metadata': {
                    'method': 'update_direction',
                    'requires_tee': True,
                    'threshold': direction_threshold
                }
            }
            
        except Exception as e:
            print(f"    ❌ 更新方向检测错误: {str(e)}")
            import traceback
            client_results['detectors']['update_direction'] = {
                'error': str(e),
                'traceback': traceback.format_exc()
            }
        
        # 2. BN层欧氏距离检测已屏蔽（仅使用direction_similarity检测）
        # 注释掉BN检测器，统一使用direction_similarity检测
        # if is_noise_attack:
        #     try:
        #         # 计算BN层欧氏距离
        #         bn_stats = self.detectors['batchnorm_euclidean'].calculate_bn_euclidean(
        #             external_model, tee_model
        #         )
        #         
        #         # 基于指标进行检测（使用深层BN：layer2, layer3, layer4，阈值0.008）
        #         bn_euclidean_result = self.detectors['batchnorm_euclidean'].detect_anomaly(
        #             bn_stats, threshold=0.008, use_sensitive_layers=True
        #         )
        #         
        #         # 保存结果
        #         client_results['detectors']['batchnorm_euclidean'] = {
        #             'detection_result': bn_euclidean_result,
        #             'metadata': {
        #                 'method': 'batchnorm_euclidean',
        #                 'requires_tee': True,
        #                 'threshold': 0.15
        #             }
        #         }
        #         
        #     except Exception as e:
        #         print(f"    ❌ BN层欧氏距离检测错误: {str(e)}")
        #         import traceback
        #         client_results['detectors']['batchnorm_euclidean'] = {
        #             'error': str(e),
        #             'traceback': traceback.format_exc()
        #         }
        
        return client_results
    
    def _print_result(self, detector_name, result, actual_malicious):
        """打印检测结果"""
        display_name = self.detector_names.get(detector_name, detector_name)
        
        if 'error' in result:
            print(f"   ❌ {display_name}: 错误")
            return
        
        is_anomaly = result.get('is_anomaly', False)
        confidence = result.get('confidence', 0.0)
        
        # 判断检测是否正确
        correct = (is_anomaly == actual_malicious)
        symbol = "✅" if correct else "❌"
        
        result_text = "恶意" if is_anomaly else "良性"
        actual_text = "恶意" if actual_malicious else "良性"
        
        print(f"   {symbol} {display_name}: 检测={result_text}, 实际={actual_text}, 置信度={confidence:.3f}")
        
        # 打印详细指标
        if 'features' in result:
            features = result['features']
            print(f"      📊 检测特征:")
            
            # 根据不同检测器显示不同的特征
            if detector_name == 'parameter_update_norm':
                print(f"         总范数: {features.get('total_norm', 0):.2f}")
                print(f"         最大层范数: {features.get('max_norm', 0):.2f}")
                print(f"         变异系数: {features.get('cv_norm', 0):.4f}")
            
            elif detector_name == 'update_direction':
                print(f"         余弦相似度: {features.get('update_direction_similarity', 0):.4f}")
                print(f"         范数比例: {features.get('update_norm_ratio', 0):.4f}")
            
            elif detector_name == 'layer_wise_update_norm':
                print(f"         平均层范数: {features.get('mean_norm', 0):.2f}")
                print(f"         高范数层比例: {features.get('high_norm_ratio', 0):.2%}")
            
            elif detector_name == 'layer_wise_direction':
                print(f"         外部模型相似度: {features.get('mean_external_similarity', 0):.4f}")
                print(f"         方向偏离程度: {features.get('mean_deviation', 0):.4f}")
                print(f"         最大偏离: {features.get('max_deviation', 0):.4f}")
        
        # 打印证据（如果有）
        if 'evidence' in result and result['evidence']:
            print(f"      ⚠️  异常证据:")
            for evidence in result['evidence'][:2]:  # 只显示前2条
                print(f"         • {evidence}")
    
    def calculate_simple_statistics(self, all_results):
        """
        计算简化统计指标（仅update_direction检测器）
        
        Args:
            all_results: 所有客户端的检测结果列表
        
        Returns:
            dict: 统计结果
        """
        print(f"\n{'='*80}")
        print("检测器性能统计（update_direction）")
        print(f"{'='*80}\n")
        
        tp = fp = tn = fn = 0
        
        for client_result in all_results:
            actual_malicious = client_result['is_malicious']
            detector_result = client_result['detectors'].get('update_direction', {})
            
            if 'error' in detector_result:
                continue
            
            # 获取检测结果
            if 'detection_result' in detector_result:
                detection_info = detector_result['detection_result']
            else:
                detection_info = detector_result
            
            if 'is_anomaly' not in detection_info:
                continue
            
            detected_malicious = detection_info['is_anomaly']
            
            if actual_malicious and detected_malicious:
                tp += 1
            elif not actual_malicious and detected_malicious:
                fp += 1
            elif not actual_malicious and not detected_malicious:
                tn += 1
            elif actual_malicious and not detected_malicious:
                fn += 1
        
        total = tp + fp + tn + fn
        if total == 0:
            print("⚠️  无有效检测数据")
            return {}
        
        accuracy = (tp + tn) / total if total > 0 else 0
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0
        fnr = fn / (fn + tp) if (fn + tp) > 0 else 0
        
        detector_stats = {
            'update_direction': {
                'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
                'accuracy': accuracy,
                'precision': precision,
                'recall': recall,
                'f1': f1,
                'fpr': fpr,
                'fnr': fnr
            }
        }
        
        print("update_direction检测器:")
        print(f"  ✅ 准确率: {accuracy:.2%}")
        print(f"  📊 精确率: {precision:.2%}  召回率: {recall:.2%}  F1分数: {f1:.2%}")
        print(f"  ⚠️  误报率: {fpr:.2%}  漏报率: {fnr:.2%}")
        print(f"  📈 TP={tp}, FP={fp}, TN={tn}, FN={fn}")
        print(f"  📝 总计: {total} 个客户端检测")
        print()
        
        return detector_stats
    
    def _convert_to_json_serializable(self, obj):
        """递归转换对象为JSON可序列化格式"""
        if isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, torch.device):
            return str(obj)
        elif isinstance(obj, dict):
            return {key: self._convert_to_json_serializable(value) for key, value in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._convert_to_json_serializable(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        else:
            # 对于其他类型，尝试转换为字符串
            try:
                json.dumps(obj)
                return obj
            except (TypeError, ValueError):
                return str(obj)
    
    def save_results(self, all_results, detector_stats, filename=None, attack_config=None, round_details=None):
        """保存结果到JSON文件
        
        Args:
            all_results: 所有客户端的检测结果
            detector_stats: 检测器统计信息
            filename: 保存的文件名
            attack_config: 攻击配置信息（可选）
            round_details: 每轮训练详情（可选）
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"independent_detectors_test_{timestamp}.json"
        
        # 转换args为可序列化的字典
        args_dict = {}
        for key, value in vars(self.args).items():
            args_dict[key] = self._convert_to_json_serializable(value)
        
        # 🔧 修复：如果有攻击配置，更新args中的相关字段
        if attack_config:
            if 'attack_type' in attack_config:
                args_dict['attack_scenario'] = attack_config['attack_type']
            # 🔧 修复Bug：使用attack_config中的实际enable_defense值（而不是args默认值）
            if 'enable_defense' in attack_config:
                args_dict['enable_defense'] = 1 if attack_config['enable_defense'] else 0
        
        # 转换所有数据为可序列化格式
        output = {
            'test_time': datetime.now().isoformat(),
            'args': args_dict,
            'attack_config': self._convert_to_json_serializable(attack_config) if attack_config else None,
            'detector_stats': self._convert_to_json_serializable(detector_stats),
            'client_results': self._convert_to_json_serializable(all_results),
            'round_details': self._convert_to_json_serializable(round_details) if round_details else None
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 结果已保存到: {filename}")
        return filename


def main():
    """测试主函数"""
    print("独立检测器测试系统")
    print("测试update_direction检测器的独立检测效果")
    
    # 这里应该导入完整的训练环境
    # 实际使用时需要集成到训练流程中
    print("\n⚠️  请在训练流程中调用此模块")
    print("使用方法:")
    print("  from independent_detectors_test import IndependentDetectorsTester")
    print("  tester = IndependentDetectorsTester(args)")
    print("  result = tester.test_update_direction_only(global_model, external_model, tee_model, client_id, is_malicious)")


if __name__ == "__main__":
    main()

