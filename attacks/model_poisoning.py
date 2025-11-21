"""
模型投毒攻击模块
实现模型层面的投毒攻击方法（Model Poisoning）

与数据投毒（Data Poisoning）的区别：
- 数据投毒：在训练前修改数据（label flipping, noise injection）
- 模型投毒：在训练后优化模型参数（PoisonedFL, multi-round consistency）
"""

import torch
import torch.nn as nn
import copy
import numpy as np
from abc import ABC, abstractmethod


class ModelPoisoningBase(ABC):
    """模型投毒攻击基类"""
    
    def __init__(self, args, device):
        """
        Args:
            args: 训练参数
            device: 计算设备
        """
        self.args = args
        self.device = device
        self.attack_history = []  # 记录历史攻击信息（用于多轮一致性）
    
    @abstractmethod
    def craft_malicious_update(self, client_model, global_model, round_idx, **kwargs):
        """
        制作恶意模型更新的抽象方法
        
        Args:
            client_model: 客户端训练后的模型
            global_model: 当前全局模型
            round_idx: 当前训练轮次
            **kwargs: 其他参数
            
        Returns:
            poisoned_model: 经过恶意优化的模型
        """
        pass
    
    def get_model_update(self, client_model, global_model):
        """计算模型更新向量（client - global）"""
        update = {}
        client_state = client_model.state_dict()
        global_state = global_model.state_dict()
        
        for key in client_state.keys():
            update[key] = client_state[key] - global_state[key]
        
        return update
    
    def apply_update_to_model(self, global_model, update, scale=1.0):
        """将更新应用到全局模型上"""
        poisoned_model = copy.deepcopy(global_model)
        global_state = global_model.state_dict()
        
        poisoned_state = {}
        for key in global_state.keys():
            poisoned_state[key] = global_state[key] + scale * update[key]
        
        poisoned_model.load_state_dict(poisoned_state)
        return poisoned_model
    
    def flatten_params(self, state_dict):
        """展平模型参数为一维向量"""
        return torch.cat([param.flatten() for param in state_dict.values()])
    
    def unflatten_params(self, flat_params, reference_state_dict):
        """将一维向量恢复为模型参数字典"""
        state_dict = {}
        offset = 0
        
        for key, param in reference_state_dict.items():
            param_shape = param.shape
            param_size = param.numel()
            state_dict[key] = flat_params[offset:offset+param_size].reshape(param_shape)
            offset += param_size
        
        return state_dict


class PoisonedFLAttack(ModelPoisoningBase):
    """
    PoisonedFL攻击：多轮一致性模型投毒攻击
    
    论文：Model Poisoning Attacks to Federated Learning via Multi-Round Consistency
    
    核心思想：
    1. 恶意客户端正常训练模型
    2. 训练后通过优化调整模型更新方向
    3. 使恶意更新在多轮中保持一致性，增强攻击效果且难以被检测
    
    攻击流程：
    ┌─────────────┐
    │ 正常训练    │  w^t = Train(w^{t-1}, D_local)
    └─────────────┘
           │
           ▼
    ┌─────────────┐
    │ 计算更新    │  Δw^t = w^t - w^{t-1}
    └─────────────┘
           │
           ▼
    ┌─────────────┐
    │ 优化攻击    │  Δw^t* = Optimize(Δw^t, history)
    │ (多轮一致性) │  - 保持方向一致
    └─────────────┘  - 调整幅度
           │
           ▼
    ┌─────────────┐
    │ 返回恶意模型 │  w^t* = w^{t-1} + Δw^t*
    └─────────────┘
    """
    
    def __init__(self, args, device, attack_strength=1.0, consistency_weight=0.5):
        """
        Args:
            args: 训练参数
            device: 计算设备
            attack_strength: 攻击强度 (缩放因子λ，默认1.0)
            consistency_weight: 保留（兼容性，但PoisonedFL不使用）
        """
        super().__init__(args, device)
        self.attack_strength = attack_strength
        self.sign_vector = None  # 固定的随机符号向量 s (多轮一致性的关键)
        self.prev_global_model = None  # 上一轮的全局模型
        self.prev_malicious_update = None  # 上一轮的恶意更新（用于估计）
        self.last_updated_round = -1  # 记录上次更新状态的轮次（避免同一轮重复更新）
        
    def craft_malicious_update(self, client_model, global_model, round_idx, **kwargs):
        """
        制作恶意模型更新（PoisonedFL算法 - 论文正确实现）
        
        论文：Model Poisoning Attacks to Federated Learning via Multi-Round Consistency (CVPR 2025)
        
        核心思想：
        1. 固定随机符号向量 s ∈ {-1, +1}^d (第0轮生成，之后不变)
        2. 恶意更新 = s ⊙ (λ^t * v^t)
           - λ^t: 缩放因子（攻击强度）
           - v^t: 单位幅度向量（从全局模型差异估计）
        3. 多轮累积朝同一随机方向 → 破坏全局模型
        
        - ✅ 正确：固定随机方向 → 破坏模型 → 准确率下降
        """
        # 1. 第0轮：生成固定的随机符号向量 s (多轮一致性的核心)
        normal_update = self.get_model_update(client_model, global_model)
        normal_update_flat = self.flatten_params(normal_update)
        
        if self.sign_vector is None:
            # 随机生成 {-1, +1}，固定不变
            self.sign_vector = torch.sign(torch.randn_like(normal_update_flat))
            self.sign_vector[self.sign_vector == 0] = 1  # 避免0
            print(f"      [PoisonedFL] 生成固定随机符号向量 (维度: {len(self.sign_vector)})")
        
        # 2. 估计单位幅度向量 v^t（论文公式6）
        if round_idx > 0 and self.prev_global_model is not None and self.prev_malicious_update is not None:
            # g^{t-1} = w^{t-1} - w^{t-2} (上一轮的聚合更新)
            global_diff = self.get_model_update(global_model, self.prev_global_model)
            global_diff_flat = self.flatten_params(global_diff)
            
            # 检查全局差异是否有效
            global_diff_norm = torch.norm(global_diff_flat)
            prev_malicious_norm = torch.norm(self.prev_malicious_update)
            
            if global_diff_norm > 1e-6 and prev_malicious_norm > 1e-6:
                # 论文公式6：v^t = |g^{t-1} - (||g^{t-1}|| / ||k^{t-1}⊙s||) * (k^{t-1}⊙s)| / ||...|||
                # 从全局差异中减去恶意更新的归一化贡献
                prev_malicious = self.prev_malicious_update.to(self.device)
                
                # 数值稳定性：裁剪prev_malicious中的极值（防止计算时溢出）
                prev_malicious = torch.clamp(prev_malicious, min=-1e6, max=1e6)
                
                scaling = global_diff_norm / prev_malicious_norm
                # 数值稳定性：裁剪scaling（保留较大上限，贴近论文设计）
                # 100倍足够覆盖模型崩溃等极端场景，同时防止数值溢出
                scaling = min(scaling, 100.0)
                
                estimated_benign = global_diff_flat - scaling * prev_malicious
                
                # 🔍 检查estimated_benign是否包含NaN/Inf（多层防护）
                if torch.isnan(estimated_benign).any() or torch.isinf(estimated_benign).any():
                    print(f"      [警告] estimated_benign包含NaN/Inf（scaling={scaling:.2f}），使用正常更新幅度")
                    unit_magnitude = torch.abs(normal_update_flat) / (torch.norm(normal_update_flat) + 1e-10)
                else:
                    estimated_benign_norm = torch.norm(estimated_benign)
                    if estimated_benign_norm > 1e-6:
                        unit_magnitude = torch.abs(estimated_benign) / estimated_benign_norm
                    else:
                        # 如果估计的良性更新接近0，回退到使用当前正常训练
                        unit_magnitude = torch.abs(normal_update_flat) / (torch.norm(normal_update_flat) + 1e-10)
            else:
                # 如果全局差异太小，使用当前正常训练的幅度分布
                unit_magnitude = torch.abs(normal_update_flat) / (torch.norm(normal_update_flat) + 1e-10)
        else:
            # 第0轮：使用正常训练更新的幅度分布
            unit_magnitude = torch.abs(normal_update_flat) / (torch.norm(normal_update_flat) + 1e-10)
        
        # 3. 计算缩放因子 λ^t（论文公式7: λ^t = c^t · ||w^{t-1} - w^{t-2}||）
        if round_idx > 0 and self.prev_global_model is not None:
            # 计算全局模型差异范数（即上一轮的聚合更新范数）
            global_diff = self.get_model_update(global_model, self.prev_global_model)
            global_diff_flat = self.flatten_params(global_diff)
            global_diff_norm = torch.norm(global_diff_flat).item()
            
            # 检查全局差异是否有效（避免同一轮内重复调用导致差异为0）
            if global_diff_norm < 1e-6:
                # 全局模型未变化，使用正常更新范数作为估计
                global_diff_norm = torch.norm(normal_update_flat).item()
                print(f"      [警告] 全局模型差异过小(≈0)，使用正常更新范数估计: {global_diff_norm:.4f}")
            
            # 论文公式7：λ^t = c^t · ||w^{t-1} - w^{t-2}||
            # attack_strength 对应论文中的 c^t（论文默认 c_0=8）
            lambda_t = self.attack_strength * global_diff_norm
            
            # 数值稳定性：自适应裁剪lambda_t（防止NaN但保持攻击有效性）
            normal_norm = torch.norm(normal_update_flat).item()
            
            # 策略：基于正常更新范数的倍数裁剪（自适应，适用于不同数据集和模型）
            # 论文设计：恶意更新 = c^t × ||Δw||，c^t=8时，理论上恶意范数≈8×正常范数
            # 考虑数值稳定性：允许最多12倍（略大于论文设计，给予一定余量但不过分）
            max_ratio = 12.0
            max_lambda = normal_norm * max_ratio
            
            # 检查并裁剪
            if lambda_t > max_lambda:
                print(f"      [稳定性] λ^t={lambda_t:.2f}过大，裁剪到{max_lambda:.2f}（正常范数={normal_norm:.2f}×{max_ratio:.0f}）")
                lambda_t = max_lambda
            elif torch.isnan(torch.tensor(lambda_t)):
                print(f"      [错误] λ^t为NaN，使用备用值")
                lambda_t = self.attack_strength * normal_norm
            
            # 记录未裁剪的原始值（用于分析）
            if lambda_t < self.attack_strength * global_diff_norm:
                original_lambda = self.attack_strength * global_diff_norm
                # 不打印，避免刷屏，只在需要时取消注释
                # print(f"      [调试] 原始λ^t={original_lambda:.2f}，裁剪后={lambda_t:.2f}")
        else:
            # 第0轮或第一次攻击：使用正常更新范数估计
            estimated_norm = torch.norm(normal_update_flat).item()
            lambda_t = self.attack_strength * estimated_norm
        
        # 4. 计算幅度向量：k^t = λ^t * v^t
        magnitude_vector = lambda_t * unit_magnitude
        
        # 数值稳定性检查：确保magnitude_vector没有NaN或Inf
        if torch.isnan(magnitude_vector).any() or torch.isinf(magnitude_vector).any():
            print(f"      [错误] magnitude_vector包含NaN/Inf，回退到简单攻击")
            # 回退策略：使用固定幅度的随机方向攻击
            fallback_magnitude = torch.norm(normal_update_flat).item() * self.attack_strength
            magnitude_vector = torch.ones_like(normal_update_flat) * fallback_magnitude / len(normal_update_flat)**0.5
        
        # 4. 构造恶意更新：g_i^t = s ⊙ k^t (element-wise乘积)
        malicious_update_flat = self.sign_vector * magnitude_vector
        
        # 🔍 最终NaN检查：确保恶意更新没有NaN/Inf
        if torch.isnan(malicious_update_flat).any() or torch.isinf(malicious_update_flat).any():
            print(f"      [错误] malicious_update_flat包含NaN/Inf，使用保守回退攻击")
            # 保守回退攻击：固定符号向量 × 正常幅度（不放大）
            # 这样即使模型已崩溃，仍保持攻击但幅度较小，不会加剧NaN
            fallback_magnitude = torch.norm(normal_update_flat).item()  # 不乘以attack_strength
            # 使用正常更新的幅度分布（而不是均匀分布）
            safe_magnitude_vector = torch.abs(normal_update_flat)
            safe_magnitude_vector = safe_magnitude_vector * (fallback_magnitude / (torch.norm(safe_magnitude_vector) + 1e-10))
            malicious_update_flat = self.sign_vector * safe_magnitude_vector
            print(f"      [回退] 使用保守攻击（固定符号×正常幅度分布），范数={fallback_magnitude:.4f}")
        
        # 🔧 暂时禁用客户端扰动（调试NaN问题）
        # 扰动强度：0.05 * 恶意更新范数（5%随机噪声）
        # if 'client_id' in kwargs:
        #     torch.manual_seed(kwargs['client_id'])  # 基于client_id的确定性随机
        #     noise = torch.randn_like(malicious_update_flat) * 0.05 * torch.norm(malicious_update_flat)
        #     malicious_update_flat = malicious_update_flat + noise
        
        # 5. 恢复为参数字典
        malicious_update = self.unflatten_params(malicious_update_flat, normal_update)
        
        # 6. 应用恶意更新到全局模型
        # ⚠️ 注意：所有恶意客户端返回相同的模型(global_model + malicious_update)
        # 这是论文的设计：多轮一致性需要固定方向，所以恶意客户端忽略本地训练
        poisoned_model = self.apply_update_to_model(
            global_model,  # 基于全局模型（论文设计）
            malicious_update,  # 加上恶意更新
            scale=1.0
        )
        
        # 7. 保存状态（用于下一轮估计）
        # ⚠️ 关键：只在每轮第一次调用时更新状态，避免同一轮内重复更新
        if self.last_updated_round < round_idx:
            self.prev_global_model = copy.deepcopy(global_model)
            self.prev_malicious_update = malicious_update_flat.detach().cpu()
            self.last_updated_round = round_idx
        
        # 8. 记录攻击历史并打印调试信息
        normal_norm = torch.norm(normal_update_flat).item()
        malicious_norm = torch.norm(malicious_update_flat).item()
        sign_consistency = torch.mean((self.sign_vector == torch.sign(malicious_update_flat)).float()).item()
        
        # 🔍 最终安全检查：记录但继续（前面已经处理过NaN了）
        if torch.isnan(torch.tensor(malicious_norm)):
            # 理论上不应该到这里，因为前面已经处理了
            print(f"      [⚠️  异常] 恶意更新范数仍为NaN，这不应该发生！")
            print(f"         正常范数={normal_norm:.4f}，将使用可能包含NaN的模型")
            # 继续执行，不返回client_model（避免攻击失效）
        
        self.attack_history.append({
            'round': round_idx,
            'normal_norm': normal_norm,
            'malicious_norm': malicious_norm,
            'sign_consistency': sign_consistency,
            'lambda_t': lambda_t  # 保存实际使用的lambda_t
        })
        
        # 🔍 调试：打印恶意更新信息（使用实际计算的lambda_t，而不是重新计算）
        print(f"      [调试] Round {round_idx}: 正常范数={normal_norm:.4f}, 恶意范数={malicious_norm:.4f}, 比率={malicious_norm/normal_norm:.2f}x")
        print(f"      [调试] c^t={self.attack_strength:.1f}, λ^t={lambda_t:.4f}, 符号一致性={sign_consistency:.2%}")
        
        return poisoned_model
    
    def reset_attack_history(self):
        """重置攻击历史（新实验开始时调用）"""
        self.attack_history = []
        self.sign_vector = None  # 重置符号向量（新实验重新生成）
        self.prev_global_model = None
        self.prev_malicious_update = None
        self.last_updated_round = -1  # 重置轮次追踪


# 导出攻击类
__all__ = [
    'ModelPoisoningBase',
    'PoisonedFLAttack',
]
