# 🌳 PoisonedFL功能分支完成后的Git工作流

## 📍 当前状态
- **功能分支**: `feature/add_multi_round_consistency_attack`
- **功能**: 完成PoisonedFL攻击实现和测试
- **状态**: 已验证，攻击有效，检测器工作正常

---

## 🎯 分支处理步骤

### 步骤1：清理工作目录并提交最终代码

```bash
# 1.1 清理冗余文件（先执行CLEANUP_PLAN.md中的清理）
# 创建目录
mkdir -p docs/archived
mkdir -p results

# 移动Bug调试文档到归档
git mv BUG_FIX_SUMMARY.md docs/archived/
git mv BUG_POISONEDFL_NO_EFFECT.md docs/archived/
git mv CRITICAL_BUG_FIXED.md docs/archived/

# 删除旧实验结果（不需要提交到Git）
rm independent_test_lenet5_poisonedfl_iid_20251110_165905.json
rm independent_test_lenet5_poisonedfl_iid_20251110_185146.json
rm independent_test_lenet5_poisonedfl_noniid_case5_beta0.5_20251110_193712.json

# 移动最新实验结果到results目录
mv independent_test_lenet5_poisonedfl_noniid_case5_beta0.5_20251111_002220.json results/
mv independent_test_lenet5_poisonedfl_noniid_case5_beta0.5_20251111_012610.json results/

# 1.2 添加所有更改
git add -A

# 1.3 提交清理和最终代码
git commit -m "feat: PoisonedFL攻击实现完成

功能概述：
- 实现PoisonedFL模型投毒攻击（CVPR 2025论文）
- 集成到TEE-FL框架，支持方向相似度检测
- 完成攻击效果验证和防御测试

关键文件：
- attacks/model_poisoning.py: PoisonedFL核心实现
- attacks/poisonedfl_paper_annotated.py: 论文参考实现
- test_independent_detectors_training.py: 集成测试脚本
- EXPERIMENT_ANALYSIS_20251111.md: 实验结果分析

测试结果：
- 检测器召回率: 100%
- 检测器精确率: 99.4-100%
- 攻击强度λ=5.0已验证有效
- 防御模式成功阻断所有恶意客户端

问题修复：
- 修复聚合Bug：使用投毒后的模型而非训练后的模型
- 添加NaN检查防止模型崩溃
- 修正阈值显示（0.15而非-1.0）
"
```

---

### 步骤2：推送到远程仓库

```bash
# 推送feature分支到你的fork
git push origin feature/add_multi_round_consistency_attack

# 如果之前已经推送过，使用force-with-lease（安全的强制推送）
git push --force-with-lease origin feature/add_multi_round_consistency_attack
```

---

### 步骤3：创建Pull Request（如果要合并到主分支）

#### 选项A：合并到你自己的main分支

**如果这是你自己的项目，可以直接合并：**

```bash
# 切换到main分支
git checkout main

# 更新main分支
git pull origin main

# 合并feature分支
git merge feature/add_multi_round_consistency_attack --no-ff

# 添加合并标签
git tag -a v1.0.0-poisonedfl -m "Release: PoisonedFL攻击实现完成"

# 推送main分支和标签
git push origin main
git push origin v1.0.0-poisonedfl
```

#### 选项B：创建PR到上游仓库

**如果要贡献到原始项目（xcx6/ZX666）：**

1. 在GitHub上创建Pull Request：
   - 从: `zhu-zhu666/ZX666:feature/add_multi_round_consistency_attack`
   - 到: `xcx6/ZX666:main`

2. PR标题和描述：
```markdown
# [Feature] 实现PoisonedFL模型投毒攻击

## 📋 功能概述
实现了CVPR 2025论文《Model Poisoning Attacks to Federated Learning via Multi-Round Consistency》中的PoisonedFL攻击。

## ✨ 主要特性
- ✅ 完整的PoisonedFL攻击实现（多轮一致性）
- ✅ 集成到TEE-FL检测器框架
- ✅ 方向相似度检测器验证
- ✅ 观察模式和防御模式测试

## 🔬 实验验证
- **检测性能**: 召回率100%，精确率99.4%
- **攻击效果**: λ=5.0已验证有效
- **防御效果**: 成功阻断所有170个恶意客户端

## 📝 关键文件
- `attacks/model_poisoning.py`: PoisonedFL核心实现
- `attacks/attack_manager.py`: 攻击管理器
- `test_independent_detectors_training.py`: 主测试脚本
- `EXPERIMENT_ANALYSIS_20251111.md`: 实验分析报告

## 🐛 Bug修复
- 修复聚合Bug：现在正确聚合投毒后的模型
- 添加NaN检查防止数值崩溃
- 修正检测阈值显示

## 🧪 测试
```bash
# 观察模式（无防御）
EPOCHS=20 ATTACK_TYPE=poisonedfl ENABLE_DEFENSE=0 bash run_independent_detector_test.sh

# 防御模式（启用检测器）
EPOCHS=20 ATTACK_TYPE=poisonedfl ENABLE_DEFENSE=1 bash run_independent_detector_test.sh
```

## 📊 实验结果
详见：`EXPERIMENT_ANALYSIS_20251111.md`

## ✅ Checklist
- [x] 代码实现完成
- [x] 单元测试通过
- [x] 集成测试通过
- [x] 文档更新
- [x] 实验验证
- [x] Bug修复
```

---

### 步骤4：清理feature分支（可选）

**合并后，可以删除feature分支：**

```bash
# 删除本地分支
git branch -d feature/add_multi_round_consistency_attack

# 删除远程分支
git push origin --delete feature/add_multi_round_consistency_attack
```

**注意**：
- 使用 `-d` 只能删除已合并的分支（安全）
- 如果要强制删除，使用 `-D`

---

### 步骤5：创建Release（推荐）

**如果这是重要的里程碑，创建一个Release：**

```bash
# 创建带注释的标签
git tag -a v1.0.0 -m "Release v1.0.0: PoisonedFL攻击实现

主要功能：
- PoisonedFL模型投毒攻击
- TEE-FL检测器集成
- 完整的实验验证

实验结果：
- 检测器性能: 召回率100%, 精确率99.4%
- 攻击有效性: λ=5.0验证通过
- 防御效果: 成功阻断所有恶意客户端
"

# 推送标签
git push origin v1.0.0

# 在GitHub上创建Release
# 访问: https://github.com/zhu-zhu666/ZX666/releases/new
# 选择标签 v1.0.0
# 添加Release notes（可以复制上面的内容）
# 附加实验结果文件
```

---

## 🎯 推荐工作流

### 场景1：你自己的研究项目（推荐）

```bash
# 1. 清理并提交
git add -A
git commit -m "feat: PoisonedFL攻击实现完成"

# 2. 切换到main并合并
git checkout main
git merge feature/add_multi_round_consistency_attack --no-ff

# 3. 创建版本标签
git tag -a v1.0.0-poisonedfl -m "PoisonedFL攻击实现"

# 4. 推送
git push origin main --tags

# 5. 保留feature分支（以便后续改进）
# 或删除: git branch -d feature/add_multi_round_consistency_attack
```

### 场景2：贡献到开源项目

```bash
# 1. 清理并提交
git add -A
git commit -m "feat: PoisonedFL攻击实现完成"

# 2. 推送feature分支
git push origin feature/add_multi_round_consistency_attack

# 3. 在GitHub上创建Pull Request

# 4. 等待review和合并

# 5. 合并后清理
git checkout main
git pull origin main
git branch -d feature/add_multi_round_consistency_attack
```

---

## 📁 .gitignore建议

**确保不提交大型实验文件：**

```bash
# 添加到.gitignore
echo "# 实验结果（太大，不提交）" >> .gitignore
echo "*.json" >> .gitignore
echo "results/*.json" >> .gitignore
echo "" >> .gitignore

echo "# 数据文件" >> .gitignore
echo "data/*.pt" >> .gitignore
echo "data/*.pth" >> .gitignore
echo "data/mnist/" >> .gitignore
echo "" >> .gitignore

echo "# 日志和临时文件" >> .gitignore
echo "*.log" >> .gitignore
echo "*.tmp" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore

git add .gitignore
git commit -m "chore: 更新.gitignore，忽略实验结果和数据文件"
```

---

## 🎨 分支策略建议

### Git Flow（推荐用于研究项目）

```
main          [========]  稳定版本，论文发表时的代码
  │
  ├── develop [======]    开发分支，日常开发
  │    │
  │    ├── feature/poisonedfl  [完成]  ✅
  │    ├── feature/backdoor     [计划]
  │    └── feature/byzantine    [计划]
  │
  └── release/v1.0  [===]  发布准备
```

**工作流**：
1. `feature/*` → `develop` (PR/合并)
2. `develop` → `release/vX.X` (准备发布)
3. `release/vX.X` → `main` (发布)
4. 打标签 `v1.0.0`

---

## 📊 项目里程碑

### v1.0.0-poisonedfl ✅ (当前)
- [x] PoisonedFL攻击实现
- [x] TEE-FL检测器集成
- [x] 实验验证（λ=5.0）
- [x] Bug修复（聚合、NaN检查）

### v1.1.0 (计划)
- [ ] 增加更多攻击强度测试（λ=3, 10, 15）
- [ ] 降低恶意占比到20%（符合论文）
- [ ] 对比IID vs Non-IID效果
- [ ] 生成准确率曲线图

### v2.0.0 (未来)
- [ ] 实现其他模型投毒攻击
- [ ] Byzantine攻击
- [ ] 后门攻击
- [ ] 多攻击场景对比

---

## 🚀 快速命令参考

### 提交并推送
```bash
git add -A
git commit -m "feat: PoisonedFL攻击实现完成"
git push origin feature/add_multi_round_consistency_attack
```

### 合并到main
```bash
git checkout main
git merge feature/add_multi_round_consistency_attack --no-ff
git push origin main
```

### 创建标签
```bash
git tag -a v1.0.0 -m "PoisonedFL攻击实现"
git push origin v1.0.0
```

### 清理分支
```bash
git branch -d feature/add_multi_round_consistency_attack
git push origin --delete feature/add_multi_round_consistency_attack
```

---

## ⚠️ 注意事项

1. **不要提交大文件**：
   - JSON实验结果（>100KB）
   - 数据集文件（MNIST等）
   - 模型检查点（.pt, .pth）

2. **保护main分支**：
   - 不要直接在main上开发
   - 使用feature分支开发新功能
   - 通过PR合并到main

3. **写清楚commit message**：
   - 使用约定式提交（Conventional Commits）
   - `feat:` 新功能
   - `fix:` Bug修复
   - `docs:` 文档更新
   - `test:` 测试更新
   - `chore:` 杂项（配置、清理等）

4. **定期同步上游**：
   ```bash
   git fetch upstream
   git checkout main
   git merge upstream/main
   ```

---

## 📚 相关资源

- [Git Flow](https://nvie.com/posts/a-successful-git-branching-model/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [GitHub Flow](https://guides.github.com/introduction/flow/)
