# 🔴 致命Bug：PoisonedFL攻击未被聚合

## 问题发现时间
2025-11-10 22:05

## 问题描述

**现象**：
- ✅ 攻击执行了（调试输出显示恶意更新范数15.0，比率10-16x）
- ✅ 检测器识别出恶意客户端（方向相似度-0.06）
- ❌ 准确率不下降，甚至上升（81% → 90%）

**根本原因**：
聚合时使用了**训练后的模型**，而不是**投毒后的模型**。

---

## 🐛 Bug代码

```python
# test_independent_detectors_training.py

# 第558-565行：外部训练
w_external, external_loss = local.train_external(...)
external_model.load_state_dict(w_external)  # external_model = 训练后的模型

# 第571-576行：模型投毒
external_model = attack_manager.poison_model(
    client_id=user_idx,
    client_model=external_model,
    global_model=global_model,
    round_idx=round_idx
)  # external_model = 投毒后的模型（已修改）

# 第784行：聚合（❌ Bug在这里）
w_locals.append(copy.deepcopy(w_external))  # ❌ 聚合的是 w_external（训练后）
                                            # 而不是 external_model.state_dict()（投毒后）
```

**结果**：
- 恶意客户端返回的是正常训练的模型
- 投毒后的模型完全没被聚合进去
- 所以准确率不下降

---

## ✅ 修复代码

```python
# 第784-788行（修复后）
# 聚合模型（所有轮次都执行）
if should_aggregate:
    # 🔧 关键修复：聚合投毒后的模型，不是训练后的模型
    # 对于模型投毒攻击，external_model已经被poison_model修改
    # 对于数据投毒攻击，external_model就是训练后的模型
    w_locals.append(copy.deepcopy(external_model.state_dict()))
    aggregated_clients.append(user_idx)
```

**修复原理**：
1. `poison_model()`返回的是修改后的模型对象
2. 第571行 `external_model = ...` 已经把投毒后的模型赋值给`external_model`
3. 聚合时应该使用 `external_model.state_dict()`（投毒后）
4. 而不是 `w_external`（训练后）

---

## 🔍 为什么之前没发现？

### 1. 变量命名混淆
```python
w_external        # state_dict（训练后）
external_model    # nn.Module对象（投毒后）
```

两个变量都以`external`开头，但：
- `w_external` 是训练后的state_dict（第558行）
- `external_model` 是投毒后的模型对象（第571行）

聚合时错误地使用了 `w_external`。

### 2. 数据投毒攻击不受影响

对于数据投毒攻击（label_flipping, noise_injection）：
- 只在训练前修改数据
- `w_external` 就是最终结果
- Bug不影响数据投毒攻击

对于模型投毒攻击（PoisonedFL）：
- 训练后修改模型
- `external_model` 是最终结果
- Bug导致投毒完全失效

### 3. 检测器能检测出来，但聚合没用上

```
检测器输入：external_model.state_dict()（投毒后）✅
聚合输入：w_external（训练后）❌
```

所以检测器能识别恶意客户端（方向相似度-0.06），但聚合时用的是正常模型。

---

## 📊 修复前后对比

### 修复前

```python
训练流程：
1. external_model.train()
2. w_external = external_model.state_dict()  # 保存训练结果
3. external_model.load_state_dict(w_external)
4. external_model = poison_model(external_model)  # 投毒
5. 检测器(external_model.state_dict())  # ✅ 使用投毒后的模型
6. w_locals.append(w_external)  # ❌ 聚合训练后的模型

结果：检测器能检测，但攻击未聚合
```

### 修复后

```python
训练流程：
1. external_model.train()
2. w_external = external_model.state_dict()  # 保存训练结果
3. external_model.load_state_dict(w_external)
4. external_model = poison_model(external_model)  # 投毒
5. 检测器(external_model.state_dict())  # ✅ 使用投毒后的模型
6. w_locals.append(external_model.state_dict())  # ✅ 聚合投毒后的模型

结果：检测器能检测，攻击也被聚合
```

---

## 🎯 影响范围

### 受影响的攻击类型
- ✅ **PoisonedFL**（模型投毒）：完全失效 → 已修复
- ✅ 其他模型投毒攻击（如果添加）：同样失效 → 已修复

### 不受影响的攻击类型
- ✅ **Label Flipping**（标签翻转）：正常工作
- ✅ **Noise Injection**（噪声注入）：正常工作
- ✅ **Backdoor**（后门攻击）：正常工作

**原因**：数据投毒在训练前修改数据，`w_external`本身就包含攻击效果。

---

## 🔧 其他同步修复

### 1. 阈值修复
```python
# 观察模式也使用正确的阈值（不再是-1.0）
direction_threshold = 0.15  # PoisonedFL专用阈值
```

### 2. 攻击强度增加
```python
'attack_strength': 50.0  # 从3.0 → 15.0 → 50.0
```

### 3. 添加客户端扰动
```python
# model_poisoning.py 添加5%扰动
if 'client_id' in kwargs:
    noise = torch.randn_like(...) * 0.05 * norm
    malicious_update_flat = malicious_update_flat + noise
```

---

## ✅ 验证方法

### 运行修复后的实验

```bash
EPOCHS=20 ATTACK_TYPE=poisonedfl ENABLE_DEFENSE=0 MODEL=lenet5 DATASET=mnist DATA_DISTRIBUTION=noniid bash run_independent_detector_test.sh
```

### 预期结果（λ=50.0）

```
Round 0-2: 26% → 54% → 81% (暖机，无攻击)
Round 3:   90% (攻击开始，可能还在上升)
Round 4:   85% (开始下降)
Round 5:   75% (明显下降)
Round 8:   50% (严重破坏)
Round 12:  30% (接近崩溃)
Round 20:  15% (完全破坏)
```

### 关键指标

1. **攻击强度**：
   ```
   [调试] 正常更新范数: X.XX, 恶意更新范数: 50.0, 比率: 30-50x
   [调试] 符号一致性: 100.00%, λ=50.0
   ```

2. **方向相似度**：
   ```
   良性客户端: 0.5-0.8 (正相关)
   恶意客户端: -0.3 到 0.1 (接近垂直或负相关)
   ```

3. **准确率曲线**：
   - 从Round 4-5开始持续下降
   - Round 10应该降到60%以下
   - Round 20应该降到20%以下

---

## 📝 经验教训

1. **变量命名要清晰**：
   - `w_external` vs `external_model` 容易混淆
   - 应该用 `trained_state_dict` vs `poisoned_model`

2. **模型投毒需要特殊处理**：
   - 训练后修改模型
   - 聚合时必须用修改后的模型

3. **调试信息很重要**：
   - 攻击执行了 ≠ 攻击被聚合了
   - 需要端到端验证

4. **测试覆盖不足**：
   - 单独测试了攻击代码
   - 单独测试了聚合代码
   - 但没有测试完整流程

---

## 🎯 下一步

1. ✅ Bug已修复
2. ⏳ 重新运行实验
3. ⏳ 观察准确率是否下降
4. ⏳ 验证检测器性能

**修复完成，准备重新运行！** 🚀
