# PoisonedFL 论文代码完整解析

## 📂 文件说明

论文开源代码位置：`D:\TEEFL\PoisonedFL-main\PoisonedFL-main\`

### 核心文件

1. **`byzantine.py`** - 攻击实现
   - `poisonedfl()` - PoisonedFL完整实现（详细注释已添加）
   - `random_attack()` - 随机攻击基线
   - `init_attack()` - 初始化攻击

2. **`test_agr.py`** - 主训练循环
   - 联邦学习训练流程
   - 调用攻击和防御
   - 评估准确率

3. **`nd_aggregation.py`** - 防御聚合方法
   - `median()` - 中位数聚合
   - `trim()` - Trimmed Mean
   - `simple_mean()` - 简单平均
   - `mean_norm()` - 范数约束平均

---

## 🔄 完整训练流程

### 1. 初始化阶段（第0轮）

```python
# 第463-465行：生成固定随机符号向量 s
fixed_rand = nd.sign(nd.random.normal(
    loc=0, scale=1, 
    shape=nd.concat(*[xx.reshape((-1, 1)) for xx in init_model], dim=0).shape
)).squeeze()

# 关键：这个向量在整个训练过程中固定不变！
# 这是PoisonedFL多轮一致性的核心
```

**初始化参数**：
- `sf = 8.0` - 初始缩放系数 c^0
- `fixed_rand` - 固定随机符号向量 s ∈ {-1, +1}^d
- `history = None` - 上一轮全局变化（第1轮后开始记录）
- `last_50_model = None` - 50轮前的模型（用于假设检验）
- `last_grad = None` - 上一轮恶意更新（第2轮后开始记录）

---

### 2. 每一轮训练（第e轮）

#### Step 1: 选择参与客户端（第471-472行）

```python
participating_clients = select_clients(
    range(num_workers), 
    args.participation_rate  # 例如 2.5%
)
```

#### Step 2: 良性客户端本地训练（第486-506行）

```python
# 每个良性客户端：
for i in participating_clients:
    ori_para = [当前全局模型参数]
    
    # 本地训练 local_epoch 个epoch
    for epoch in range(args.local_epoch):
        for batch in local_data:
            # 前向传播
            output = net(batch_data)
            loss = softmax_cross_entropy(output, batch_label)
            
            # 反向传播
            loss.backward()
            
            # 本地SGD更新
            param = param - lr * grad
    
    # 计算本地更新（相对于全局模型的变化）
    local_update = 当前参数 - 原始参数
    grad_list.append(local_update)
```

#### Step 3: 恶意客户端生成攻击（第482-483行 + byzantine.py）

```python
# 初始化恶意客户端的梯度（占位）
for i in range(parti_nfake):
    grad_list.append([零梯度])

# 调用攻击函数（在聚合阶段执行）
# 见下面 Step 4
```

#### Step 4: 服务器聚合（第516-529行）

```python
# 根据防御方法选择聚合策略
if args.aggregation == "median":
    return_pare_list, sf = nd_aggregation.median(
        grad_list,      # 所有客户端更新（良性+恶意占位）
        net,            # 全局模型
        lr / batch_size,
        parti_nfake,    # 恶意客户端数量
        byz,            # 攻击函数（poisonedfl）
        history,        # g^{t-1} = w^{t-1} - w^{t-2}
        fixed_rand,     # 固定符号向量 s
        init_model,     # w^0
        last_50_model,  # w^{t-50}
        last_grad,      # k^{t-1} ⊙ s
        sf,             # 当前缩放系数 c^t
        e               # 当前轮次
    )
```

**在聚合函数内部调用攻击**：

```python
# nd_aggregation.py 中
def median(grad_list, net, lr, nfake, byz, history, fixed_rand, ...):
    # 1. 先调用攻击，修改恶意客户端的更新
    grad_list, sf = byz(
        grad_list, net, lr, nfake, 
        history, fixed_rand, init_model, 
        last_50_model, last_grad, e, sf
    )
    # 此时 grad_list 前 nfake 个已被替换为恶意更新
    
    # 2. 执行防御聚合（例如中位数）
    aggregated_update = coordinate_wise_median(grad_list)
    
    # 3. 更新全局模型
    for param, update in zip(net.params, aggregated_update):
        param.set_data(param.data() + update)
    
    return grad_list, sf
```

**攻击函数内部（byzantine.py的poisonedfl函数）**：

```python
def poisonedfl(v, net, lr, nfake, history, fixed_rand, ...):
    if isinstance(history, nd.NDArray):  # 从第2轮开始
        # 1. 估计 v^t（公式6）
        v^t = estimate_unit_magnitude_vector(
            history,      # g^{t-1}
            last_grad,    # k^{t-1} ⊙ s
            fixed_rand    # s
        )
        
        # 2. 计算 λ^t（公式7）
        λ^t = sf * ||history||
        
        # 3. 假设检验（每50轮）
        if e % 50 == 0:
            G_past = w^t - w^{t-50}
            X = count(sign(G_past) == fixed_rand)
            if X < k_99:  # 攻击无效
                sf = 0.7 * sf  # 降低强度
            else:  # 攻击有效
                sf = sf  # 保持
        
        # 4. 构造恶意更新
        mal_update = λ^t * (v^t ⊙ fixed_rand)
        
        # 5. 替换前 nfake 个客户端的更新
        for i in range(nfake):
            v[i] = mal_update
    
    return v, sf
```

#### Step 5: 更新历史信息（第530-548行）

```python
# 保存本轮的恶意更新（用于下一轮估计v^t）
if parti_nfake != 0:
    last_grad = mean(return_pare_list[:parti_nfake])

# 计算本轮全局模型变化（用于下一轮计算λ^t）
current_model = [全局模型当前参数]
history = current_model - last_model
last_model = current_model

# 每50轮保存模型（用于假设检验）
if e % 50 == 0:
    last_50_model = current_model
```

---

## 🔑 关键变量流转图

```
轮次 | 固定向量 s | 历史 g^{t-1} | 上轮恶意 k^{t-1}⊙s | λ^t | 缩放系数 c^t
-----|-----------|-------------|-------------------|-----|-------------
 0   | 生成      | None        | None              | -   | 8.0
 1   | 固定      | w^1-w^0     | None              | -   | 8.0
 2   | 固定      | w^2-w^1     | 有了              | 计算 | 8.0
 3   | 固定      | w^3-w^2     | 有了              | 计算 | 8.0
...
50   | 固定      | w^50-w^49   | 有了              | 计算 | 8.0（检验）
51   | 固定      | w^51-w^50   | 有了              | 计算 | 5.6（降低）
...
100  | 固定      | w^100-w^99  | 有了              | 计算 | 调整后
```

---

## 📊 与我们ZX666实现的对比

### 相同部分 ✅

| 模块 | 论文代码 | 我们的实现 | 位置 |
|------|---------|-----------|------|
| **固定符号 s** | `fixed_rand = nd.sign(nd.random.normal(...))` | `self.sign_vector = torch.sign(torch.randn(...))` | model_poisoning.py#155 |
| **v^t估计** | 公式6完整实现 | 公式6完整实现 | model_poisoning.py#172-180 |
| **构造攻击** | `mal_update = λ^t * (v^t ⊙ s)` | `malicious_update = sign_vector * magnitude` | model_poisoning.py#196 |

### 不同部分 ⚠️

| 模块 | 论文代码 | 我们的实现 | 影响 |
|------|---------|-----------|------|
| **λ^t计算** | `λ^t = sf * ||history||` | `lambda_t = 3.0`（固定） | 无法自适应调整强度 |
| **c^t调整** | 每50轮假设检验 | 无 | 无法根据防御反馈调整 |
| **临界值** | 预计算 k_99, k_95 | 无 | 无法判断攻击是否有效 |

---

## 🎯 代码关键点总结

### 1. 多轮一致性如何实现？

```python
# 第463行：第0轮生成
fixed_rand = nd.sign(nd.random.normal(...))

# 之后每轮都用相同的 fixed_rand
# 第75行：构造恶意更新时
mal_update = lamda_succ * deviation  # deviation 包含 fixed_rand
```

**原理**：固定的 `fixed_rand` 保证每轮攻击方向一致，累积效果。

---

### 2. 为什么从第2轮开始攻击？

```python
# 第51行
if isinstance(history, nd.NDArray):
    # 需要 history（g^{t-1}）和 last_grad（k^{t-1}⊙s）
    # 第0轮：都没有
    # 第1轮：有 history，但没有 last_grad
    # 第2轮：都有了 → 开始攻击
```

**原因**：
- 需要 `history` 来估计 v^t（公式6）
- 需要 `last_grad` 来从 `history` 中去除恶意贡献

---

### 3. 假设检验何时触发？

```python
# 第61行
if e % 50 == 0:
    # 计算 G_past = w^t - w^{t-50}
    # 统计符号一致的维度数 X
    # 二项检验
    if X < k_99:
        sf = 0.7 * sf  # 降低
```

**时机**：每50轮检查一次（可配置）

**依据**：过去50轮的累积效果是否与 `fixed_rand` 一致

---

### 4. 如何传递状态？

```python
# 每轮结束时（test_agr.py#530-548）
last_grad = mean(恶意更新)     # 保存用于下轮
history = current - last        # 保存用于下轮
if e % 50 == 0:
    last_50_model = current     # 保存用于检验

# 下一轮调用攻击时传入这些参数
grad_list, sf = byz(..., history, last_grad, last_50_model, sf, ...)
```

---

## 💡 使用示例

### 运行PoisonedFL攻击

```bash
# FashionMNIST + CNN + Median聚合 + PoisonedFL攻击
python test_agr.py \
    --dataset FashionMNIST \
    --gpu 0 \
    --net cnn \
    --niter 6000 \
    --nworkers 1200 \
    --nfake 240 \
    --aggregation median \
    --byz_type poisonedfl \
    --sf 8 \
    --local_epoch 1
```

**参数说明**：
- `--nworkers 1200` - 总客户端数
- `--nfake 240` - 恶意客户端数（20%）
- `--aggregation median` - 防御方法（中位数聚合）
- `--byz_type poisonedfl` - 攻击类型
- `--sf 8` - 初始缩放系数 c^0
- `--participation_rate 0.025` - 每轮参与率（2.5%）

---

## 📈 关键数值示例

### 网络参数量与临界值

```python
# ResNet-18 (CIFAR-10)
d = 1,204,682
k_99 = 603,618  # P(X >= k_99 | Binomial(d, 0.5)) ≈ 0.01

# CNN (FashionMNIST)
d = 139,960
k_99 = 70,415

# 计算原理（正态近似）：
μ = d * 0.5
σ = sqrt(d * 0.25)
z_{0.01} ≈ 2.33
k_99 = μ + z_{0.01} * σ
```

### 缩放系数调整轨迹

```
Round 0-49:   c = 8.0
Round 50:     检验 → c = 5.6 (0.7 * 8.0)
Round 100:    检验 → c = 3.92 (0.7 * 5.6)
Round 150:    检验 → c = 2.74 (0.7 * 3.92)
...
最小值:       c = 0.5 (下界)
```

---

## 🔗 相关文件

1. **详细注释版**：`D:\TEEFL\ZX666\attacks\poisonedfl_paper_annotated.py`
   - 逐行中文注释
   - 公式对应
   - 数值示例

2. **我们的实现**：`D:\TEEFL\ZX666\attacks\model_poisoning.py`
   - 简化版（无动态调整）
   - 适用于TEE方向检测场景

3. **论文原始代码**：`D:\TEEFL\PoisonedFL-main\PoisonedFL-main\`
   - 基于MXNet
   - 完整实现（λ^t + c^t）

---

## 🎓 学习建议

1. **先理解核心概念**：
   - 固定随机符号 s → 多轮一致性
   - v^t 估计 → 形状隐蔽
   - λ^t 调整 → 强度自适应

2. **对比两种实现**：
   - 论文完整版 vs 我们简化版
   - 何时需要动态调整？
   - 何时简化版足够？

3. **实验验证**：
   - 在统计防御下测试论文版
   - 在方向检测下测试简化版
   - 对比效果差异

4. **扩展思考**：
   - 如何改进假设检验？
   - 如何对抗方向检测？
   - 如何设计更强的防御？
