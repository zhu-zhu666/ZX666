# 🛡️ Git忽略规则说明

## 📋 哪些文件不会被提交到Git

为了保持仓库精简，以下文件类型**不会被提交**到Git仓库：

---

## 🗂️ 数据集文件（太大）

### 完全忽略的目录
```
data/mnist/           # MNIST数据集
data/cifar/           # CIFAR数据集
data/cifar10/
data/cifar100/
data/imagenet/        # ImageNet数据集
data/FEMNIST/         # 联邦学习MNIST
data/shakespeare/     # Shakespeare数据集
```

### 完全忽略的文件类型
```
data/*.pt             # PyTorch张量文件
data/*.pth            # PyTorch模型文件
data/*.h5             # HDF5数据文件
data/*.hdf5
data/*.npz            # NumPy压缩数组
data/*.npy            # NumPy数组
```

### ✅ 保留的文件（会提交）
```
data/*.json           # 数据集配置文件（如mnist_100_iid.json）
data/README.md        # 数据集说明文档
```

**示例**：
- ❌ `data/mnist/train-images-idx3-ubyte` - 不提交（二进制数据）
- ✅ `data/mnist_100_iid.json` - 提交（配置文件，400KB）

---

## 📊 实验结果文件（太大）

### 完全忽略
```
results/                          # 实验结果目录
independent_test_*.json           # 所有实验结果JSON
*.json                            # 所有JSON文件（有例外）
```

### ✅ 例外（会提交）
```
!data/*.json                      # data目录下的JSON
!cluster_mappings/*.json          # 聚类映射JSON
```

**示例**：
- ❌ `independent_test_lenet5_poisonedfl_noniid_case5_beta0.5_20251111_002220.json` - 不提交（580KB）
- ❌ `results/experiment_2025.json` - 不提交
- ✅ `data/mnist_100_iid.json` - 提交（配置文件）

---

## 🤖 模型权重和检查点（太大）

```
checkpoints/          # 模型检查点目录
saved_models/         # 保存的模型目录
*.pt                  # PyTorch模型
*.pth                 # PyTorch权重
*.ckpt                # 检查点文件
*.h5                  # Keras模型
*.hdf5
*.pkl                 # Pickle文件
*.pickle
```

**示例**：
- ❌ `checkpoints/model_round_10.pt` - 不提交
- ❌ `global_model.pth` - 不提交

---

## 📝 日志文件（太多）

```
logs/                 # 日志目录
*.log                 # 所有日志文件
*.txt                 # 所有文本文件（有例外）
```

### ✅ 例外（会提交）
```
!requirements.txt     # 依赖配置
!README.txt           # 说明文档
```

---

## 🗑️ 临时文件和缓存

```
*.tmp                 # 临时文件
*.temp
__pycache__/          # Python缓存
*.pyc                 # 编译后的Python文件
.DS_Store             # macOS文件
Thumbs.db             # Windows缩略图
```

---

## 📈 训练工具日志

```
wandb/                # Weights & Biases日志
runs/                 # TensorBoard日志
tensorboard/
```

---

## ✅ 会被提交的文件类型

### 代码文件
```
*.py                  # Python源代码
*.sh                  # Shell脚本
*.bat                 # Windows批处理脚本
```

### 文档文件
```
*.md                  # Markdown文档
README.md
INSTALL.md
```

### 配置文件
```
requirements.txt      # Python依赖
.gitignore
data/*.json           # 数据集配置（小文件）
```

---

## 🔍 如何检查哪些文件会被提交

### 方法1：查看git status
```bash
git status
```
显示将要提交的文件，如果看到大文件，说明.gitignore没生效。

### 方法2：模拟添加（不实际添加）
```bash
git add -A --dry-run
```
显示哪些文件将被添加，检查是否有大文件。

### 方法3：查看特定文件是否被忽略
```bash
git check-ignore -v data/mnist/train-images-idx3-ubyte
```
如果有输出，说明文件被忽略；如果没有输出，说明会被提交。

---

## 📏 文件大小限制建议

### GitHub推荐
- **单文件**: < 50MB（警告）, < 100MB（拒绝）
- **仓库总大小**: < 1GB（推荐）

### 我们的项目
- ✅ **提交**: < 1MB的配置和文档
- ⚠️ **谨慎**: 1-10MB的文件（如数据集配置）
- ❌ **禁止**: > 10MB的文件（如数据集、模型、结果）

---

## 🚨 常见错误

### 错误1：提交了数据集
```bash
# 问题
git add data/mnist/

# 解决
git reset data/mnist/
rm -rf data/mnist/.git*
```

### 错误2：提交了实验结果
```bash
# 问题
git add independent_test_*.json

# 解决
git reset independent_test_*.json
mv independent_test_*.json results/
```

### 错误3：已经提交了大文件
```bash
# 从Git历史中删除大文件
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch data/mnist/*' \
  --prune-empty --tag-name-filter cat -- --all

# 强制推送（危险！会重写历史）
git push origin --force --all
```

---

## 📦 数据集和结果的管理方式

### 方案1：Git LFS（推荐）
使用Git Large File Storage管理大文件：
```bash
git lfs install
git lfs track "data/mnist/*"
git lfs track "*.json"
git add .gitattributes
```

### 方案2：外部存储
- Google Drive
- Baidu Netdisk
- 实验室服务器

### 方案3：数据集下载脚本
在README中提供下载链接和脚本：
```bash
# download_data.sh
wget http://yann.lecun.com/exdb/mnist/train-images-idx3-ubyte.gz
wget http://yann.lecun.com/exdb/mnist/train-labels-idx1-ubyte.gz
```

---

## ✅ 提交前检查清单

运行 `prepare_commit.bat`（Windows）或 `prepare_commit.sh`（Linux/Mac）会自动：

- [x] 创建必要的目录（`docs/archived`, `results`）
- [x] 移动Bug文档到归档目录
- [x] 移动实验结果到results目录
- [x] 删除旧实验结果
- [x] 更新.gitignore规则
- [x] 检查是否有大文件将被提交

然后手动检查：
- [ ] `git status` 没有显示大文件
- [ ] 数据集目录（`data/mnist/`）不在提交列表
- [ ] 实验结果（`*.json`）不在提交列表
- [ ] 模型权重（`*.pt`, `*.pth`）不在提交列表

---

## 📚 相关资源

- [GitHub: About large files](https://docs.github.com/en/repositories/working-with-files/managing-large-files)
- [Git LFS](https://git-lfs.github.com/)
- [.gitignore模板](https://github.com/github/gitignore)
