# PoisonedFL 攻击集成文档

## 概述

**PoisonedFL**（Multi-Round Consistency Model Poisoning Attack）是一种先进的模型投毒攻击，已成功集成到ZX666项目中。

论文：*Model Poisoning Attacks to Federated Learning via Multi-Round Consistency*

---

## 攻击原理

### 与现有攻击的区别

| 攻击类型 | 层级 | 时机 | 方法 | 攻击目标 |
|---------|------|------|------|---------|
| **Label Flipping** | 数据层 | 训练前 | 直接翻转标签 | 降低准确率 |
| **Noise Injection** | 数据层 | 训练前 | 添加高斯噪声 | 降低准确率 |
| **PoisonedFL** | 模型层 | 训练后 | 固定随机方向多轮累积 | **破坏全局模型** ⭐ |

### 核心思想（CVPR 2025论文）

```
⚠️ 重要：已修复为论文正确实现


正确理解（当前实现）：
  固定随机方向 → 破坏模型 → 准确率下降 ✅
```

**PoisonedFL流程**：
```
第0轮：生成固定随机符号向量 s ∈ {-1, +1}^d
     ↓
每一轮：恶意更新 = s ⊙ (λ^t * v^t)
     ↓
多轮累积：Σ(恶意更新) 朝同一随机方向
     ↓
结果：全局模型偏离最优 → 错误率大幅上升
```

**关键特性**：
1. **固定随机方向 s**：第0轮随机生成，之后所有轮次保持不变（多轮一致性）
2. **动态幅度调整 λ^t * v^t**：从全局模型差异估计良性客户端的幅度分布
3. **累积破坏**：多轮更新叠加朝同一方向 → 全局模型被推向随机点

---

## 实现细节

### 1. 攻击算法

```python
# 论文正确实现的伪代码
def poisonedfl_attack(client_model, global_model, round_idx):
    # 1. 第0轮：生成固定随机符号向量 s ∈ {-1, +1}^d
    if sign_vector is None:
        sign_vector = random_signs(model_dim)  # 固定不变！
    
    # 2. 估计单位幅度向量 v^t
    if round_idx > 0:
        # 从全局模型差异估计良性幅度分布
        v_t = estimate_benign_magnitude(global_diff)
    else:
        # 第0轮：使用正常训练的幅度分布
        v_t = abs(client_model - global_model) / norm(...)
    
    # 3. 计算恶意更新：g_i^t = s ⊙ (λ^t * v^t)
    k_t = λ * v_t  # 幅度向量
    Δw_malicious = sign_vector ⊙ k_t  # element-wise乘积
    
    # 4. 返回恶意模型
    return global_model + Δw_malicious
    
    # 关键：sign_vector 固定 → 多轮累积朝同一随机方向 → 破坏全局模型
```

### 2. 代码结构

```
attacks/
├── data_poisoning.py          # 数据投毒攻击（原有）
├── model_poisoning.py         # 模型投毒攻击（新增）⭐
├── attack_manager.py          # 攻击管理器（扩展）⭐
└── config.py                  # 攻击配置（更新）⭐
```

### 3. 集成位置

在训练流程中的位置：

```
训练轮次 Round i
    │
    ├─> 外部模型训练（正常训练）
    │   └─> w_external = train_external(...)
    │
    ├─> 模型投毒（如果是恶意客户端）⭐ 新增
    │   └─> w_external = poison_model(w_external, global_model, round_i)
    │
    ├─> TEE模型训练（干净数据）
    │   └─> w_tee = train_tee_secure(...)
    │
    ├─> 检测
    │   └─> similarity = cos(Δw_external, Δw_tee)
    │
    └─> 聚合决策
```

---

## 使用方法

### 1. 基础使用

```bash
# PoisonedFL攻击（默认配置）
ATTACK_TYPE=poisonedfl MODEL=lenet5 DATASET=mnist ./run_independent_detector_test.sh
```

**参数说明**：
- 攻击强度：1.0（保持原幅度）
- 一致性权重：0.5（兼容性参数，PoisonedFL不使用）
- 恶意客户端比例：50%

**注意**：当前实现为论文核心版本，其他变体（强化版、自适应版等）已删除以保持代码简洁

---

## 对比实验

### 实验1：数据投毒 vs 模型投毒

```bash
# 1. 标签翻转（数据投毒）
ATTACK_TYPE=label_flipping DATASET=mnist EPOCHS=20 ./run_independent_detector_test.sh

# 2. PoisonedFL（模型投毒）
ATTACK_TYPE=poisonedfl DATASET=mnist EPOCHS=20 ./run_independent_detector_test.sh

# 对比：检测率、攻击成功率
```

### 实验2：IID vs Non-IID环境

```bash
# 1. IID环境
ATTACK_TYPE=poisonedfl DATA_DISTRIBUTION=iid ./run_independent_detector_test.sh

# 2. Non-IID环境（中度异构）
ATTACK_TYPE=poisonedfl DATA_DISTRIBUTION=noniid NONIID_CASE=2 ./run_independent_detector_test.sh

# 3. Non-IID环境（重度异构）
ATTACK_TYPE=poisonedfl DATA_DISTRIBUTION=noniid NONIID_CASE=3 ./run_independent_detector_test.sh
```

---

## 检测能力评估

### ZX666的检测机制能否防御PoisonedFL？

**检测原理**：
```
方向相似度检测：
similarity = cos(Δw_external, Δw_tee)

if similarity < threshold:
    判定为恶意 → 拒绝聚合
```

**PoisonedFL的挑战**：
1. ✅ 多轮一致性可能使更新累积
2. ✅ 固定随机方向可能难以检测（与论文Multi-Krum等统计防御对比）
3. ❌ 但TEE模型训练在干净数据上，**方向检测**能有效识别随机方向

**预期结果**：
- **论文场景（Multi-Krum等统计防御）**：PoisonedFL通过动态调整λ^t和假设检验可能逃避检测
- **TEE方向检测**：固定随机方向与良性方向差异显著，预期**高检测率**

---

## 结果分析

### 输出文件格式

```json
{
  "config": {
    "attack_scenario": "poisonedfl",
    "attack_strength": 1.0,
    "consistency_weight": 0.5
  },
  "rounds": [
    {
      "round": 3,
      "detection_results": [
        {
          "client_id": 10,
          "is_malicious": true,
          "detected_as_malicious": true/false,
          "detectors": {
            "update_direction": {
              "detection_result": {
                "is_malicious": true/false,
                "features": {
                  "update_direction_similarity": 0.XX
                }
              }
            }
          }
        }
      ]
    }
  ],
  "final_statistics": {
    "accuracy": 0.XX,
    "precision": 0.XX,
    "recall": 0.XX,
    "f1_score": 0.XX
  }
}
```

### 关键指标

1. **检测率（Recall）**：
   ```
   检测到的恶意客户端数 / 实际恶意客户端数
   ```
   - 越高越好（说明防御有效）

2. **精确率（Precision）**：
   ```
   检测正确的恶意客户端数 / 检测为恶意的客户端数
   ```
   - 越高越好（说明误报少）

3. **F1分数**：
   ```
   2 * (Precision * Recall) / (Precision + Recall)
   ```
   - 综合评估指标

4. **全局模型准确率**：
   - 攻击成功 → 准确率下降
   - 防御成功 → 准确率保持

---

## 实验建议

### 快速验证（调试用）

```bash
# 2轮快速测试
EPOCHS=2 ATTACK_TYPE=poisonedfl MODEL=lenet5 DATASET=mnist ./run_independent_detector_test.sh
```

### 完整实验（论文用）

```bash
# 50轮完整训练
EPOCHS=50 ATTACK_TYPE=poisonedfl MODEL=resnet DATASET=cifar10 \
DATA_DISTRIBUTION=noniid NONIID_CASE=2 ./run_independent_detector_test.sh
```

### 批量对比实验

```bash
#!/bin/bash
# 创建实验脚本
cat > run_poisonedfl_experiments.sh << 'EOF'
#!/bin/bash

echo "开始PoisonedFL对比实验..."

# 实验1: 标签翻转（基线）
echo "实验1: Label Flipping"
ATTACK_TYPE=label_flipping DATASET=mnist EPOCHS=20 ./run_independent_detector_test.sh
sleep 2

# 实验2: 噪声注入（基线）
echo "实验2: Noise Injection"
ATTACK_TYPE=noise_injection DATASET=mnist EPOCHS=20 ./run_independent_detector_test.sh
sleep 2

# 实验3: PoisonedFL（论文实现）
echo "实验3: PoisonedFL"
ATTACK_TYPE=poisonedfl DATASET=mnist EPOCHS=20 ./run_independent_detector_test.sh

echo "所有实验完成！"
EOF

chmod +x run_poisonedfl_experiments.sh
./run_poisonedfl_experiments.sh
```

---

## 注意事项

### 1. 硬件要求

- **GPU内存**：推荐 >= 8GB
- **系统内存**：推荐 >= 16GB
- PoisonedFL需要额外的模型复制和优化计算

### 2. 性能考虑

- 模型投毒会增加每轮训练时间（约10-20%）
- 多轮一致性需要维护历史信息

### 3. 参数调优

| 参数 | 范围 | 建议 | 效果 |
|------|------|------|------|
| `attack_strength` | 0.5-3.0 | 1.0-2.0 | 缩放因子λ，越高攻击越强但越容易被检测 |

**注意**：
- `consistency_weight` 为兼容性参数，PoisonedFL论文实现不使用
- 论文完整实现应包含动态λ^t和假设检验（当前为简化版）

---

## 故障排查

### 问题1：模型投毒未生效

**症状**：恶意客户端行为与良性客户端无差异

**检查**：
```bash
# 确认攻击类型正确
echo $ATTACK_TYPE  # 应该是 poisonedfl

# 查看训练日志是否有 "[🔴 模型投毒]" 标记
```

### 问题2：内存不足

**症状**：CUDA out of memory

**解决**：
```bash
# 减少批次大小或本地训练轮次
# 或使用更小的模型/数据集
MODEL=lenet5 DATASET=mnist ATTACK_TYPE=poisonedfl ./run_independent_detector_test.sh
```

### 问题3：Python导入错误

**症状**：ModuleNotFoundError: No module named 'attacks.model_poisoning'

**解决**：
```bash
# 确保文件存在
ls -l attacks/model_poisoning.py

# 重新激活环境
conda activate sgx-fl
```

---

## 论文实验建议

### 实验设置

1. **数据集**：MNIST, CIFAR-10, Fashion-MNIST
2. **模型**：LeNet5, ResNet18, ResNet20
3. **数据分布**：IID, Non-IID (α=0.1, 0.5, 0.8)
4. **攻击类型**：Label Flipping, Noise Injection, PoisonedFL, PoisonedFL-Strong
5. **训练轮次**：50轮（完整实验）

### 对比维度

| 维度 | 指标 |
|------|------|
| **攻击效果** | 全局模型准确率下降幅度 |
| **隐蔽性** | 检测率（Recall）- 越低越隐蔽 |
| **防御效果** | F1分数 - 越高防御越好 |
| **鲁棒性** | 不同数据分布下的表现 |

---

## 参考资料

1. **论文**：Model Poisoning Attacks to Federated Learning via Multi-Round Consistency
2. **ZX666项目文档**：
   - `README.md` - 项目概述
   - `WORKFLOW.md` - 训练流程详解
   - `PROJECT_STRUCTURE.md` - 代码结构
3. **相关代码**：
   - `attacks/model_poisoning.py` - PoisonedFL实现
   - `attacks/attack_manager.py` - 攻击管理
   - `test_independent_detectors_training.py` - 训练集成

---

## 更新日志

- **2025-11-10**：初始版本，集成PoisonedFL攻击及其变体
  - 新增 `model_poisoning.py` 模块
  - 扩展 `AttackManager` 支持模型投毒
  - 更新训练流程集成模型投毒逻辑
  - 添加4种PoisonedFL变体

---

## 贡献者

- 基于论文算法实现
- 集成到ZX666项目框架
- 保持代码规范和工程结构

---

**祝实验顺利！如有问题请查阅文档或联系开发者。**
