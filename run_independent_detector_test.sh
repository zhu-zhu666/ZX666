#!/bin/bash
# 独立检测器测试启动脚本

# ============ 模型和数据集配置（可通过环境变量切换） ============
# 支持的组合：
#   1. resnet + cifar10 (默认)
#   2. lenet5 + mnist
#   3. resnet20 + fmnist
# 使用方法：
#   默认运行: ./run_independent_detector_test.sh
#   切换到LeNet5+MNIST: MODEL=lenet5 DATASET=mnist ./run_independent_detector_test.sh
#   切换到ResNet20+Fashion-MNIST: MODEL=resnet20 DATASET=fmnist ./run_independent_detector_test.sh
MODEL="${MODEL:-resnet}"  # 默认resnet，可选: resnet, resnet20, lenet5, vgg
DATASET="${DATASET:-cifar10}"  # 默认cifar10，可选: cifar10, mnist, fmnist

# 根据数据集自动调整参数
if [ "$DATASET" = "mnist" ]; then
    # MNIST配置（较简单，训练更快）
    NUM_USERS=100
    EPOCHS="${EPOCHS:-50}"  # 优先使用环境变量，否则默认50
    FRAC=0.2  # 暖机期固定10个客户端，暖机后根据frac选择20个（10良性+10恶意）
    LOCAL_EP=10  # MNIST简单，减少本地训练轮数
    LR=0.01
    BS=32  # MNIST批次大小
elif [ "$DATASET" = "fmnist" ]; then
    # Fashion-MNIST配置（类似MNIST但更复杂）
    NUM_USERS=100
    EPOCHS="${EPOCHS:-50}"  # 优先使用环境变量，否则默认50
    FRAC=0.2  # 暖机期固定10个客户端，暖机后根据frac选择20个（10良性+10恶意）
    LOCAL_EP=15  # Fashion-MNIST比MNIST复杂，比CIFAR-10简单
    LR=0.01
    BS=32  # Fashion-MNIST批次大小
else
    # CIFAR-10配置（默认）
    NUM_USERS=100
    EPOCHS="${EPOCHS:-50}"  # 优先使用环境变量，否则默认50
    FRAC=0.2  # 暖机期固定10个客户端，暖机后根据frac选择20个（10良性+10恶意）
    LOCAL_EP=20
    LR=0.01
    BS=64  # CIFAR-10批次大小
fi

# ============ 攻击类型设置（可切换） ============
# 可选值: 
#   数据投毒攻击（Data Poisoning）:
#   - label_flipping: 标签翻转攻击（100%翻转率）
#   - noise_injection: 噪声注入攻击（100%加噪率）
#   
#   模型投毒攻击（Model Poisoning）:
#   - poisonedfl: PoisonedFL攻击（论文实现 - 多轮一致性模型投毒）
#   
#   基线:
#   - no_attack: 无攻击
ATTACK_TYPE="${ATTACK_TYPE:-label_flipping}"  # 默认使用标签翻转
# ===============================================

# ============ 数据分布设置（可切换） ============
# 可选值:
#   - iid: 独立同分布（每个客户端数据分布相同）
#   - noniid: 非独立同分布（每个客户端数据分布不同）
DATA_DISTRIBUTION="${DATA_DISTRIBUTION:-iid}"  # 默认使用IID

# Non-IID参数（仅当DATA_DISTRIBUTION=noniid时生效）
# NONIID_CASE: 控制数据异构程度
#   1 = mild      (轻度异构) -> 自动设置: case=4, α=0.8, μ=0.01
#   2 = moderate  (中度异构, 默认) -> 自动设置: case=5, α=0.5, μ=0.1
#   3 = extreme   (重度异构) -> 自动设置: case=6, α=0.1, μ=0.5
# 说明：
#   - case >= 4 会使用Dirichlet分布方法（separate_data），正确应用α参数
#   - case < 4 使用旧的shard方法，会忽略α参数（已废弃）
#   - α(DATA_BETA)和μ(PROX_ALPHA)会根据NONIID_CASE自动映射，也可手动覆盖
NONIID_CASE="${NONIID_CASE:-2}"

# 聚合策略选择（可选）
# USE_FEDPROX: 是否使用FedProx聚合（0=FedAvg, 1=FedProx）
# - FedAvg: 简单平均，无额外约束，学习能力强
# - FedProx: 添加proximal term约束，防止客户端过度偏离全局模型
# 建议：Non-IID环境下使用FedProx，搭配极弱正则化(μ=0.01)效果更好
USE_FEDPROX="${USE_FEDPROX:-1}"  # 默认使用 FedProx

# PROX_ALPHA (μ): FedProx本地正则化强度（仅当USE_FEDPROX=1时生效）
# FedProx在本地训练时添加proximal term: loss = CE_loss + (μ/2)||w - w_global||²
# 如果设置此变量，将覆盖根据NONIID_CASE的自动映射
# PROX_ALPHA="${PROX_ALPHA:-}"

# RANDOM_SEED: 随机种子（可选）
#   - 不设置或设置为空: 使用随机种子（每次运行结果不同）
#   - 设置为具体数值: 使用固定种子（结果可复现）
# RANDOM_SEED="${RANDOM_SEED:-}"  # 默认不设置（使用随机种子）
# ===============================================

# ============ 防御开关设置（可切换） ============
# 控制检测器是否实际影响聚合决策
# ENABLE_DEFENSE=1: 🛡️ 防御模式（检测器控制聚合，拒绝恶意客户端）
# ENABLE_DEFENSE=0: 📊 观察模式（检测器仅记录数据，不影响聚合）
ENABLE_DEFENSE="${ENABLE_DEFENSE:-1}"  # 默认启用防御
# ===============================================

# ============ 检测器阈值设置（可自定义） ============
# 噪声注入攻击检测阈值
NOISE_DIRECTION_THRESHOLD="0.24"  # 方向相似度阈值（噪声注入，std=0.25优化，第4轮开始检测）
NOISE_BN_THRESHOLD="0.008"        # BatchNorm欧氏距离阈值（深层）

# 标签翻转攻击检测阈值（统一为0.1）
LABEL_DIRECTION_THRESHOLD="0.1"  # 标签翻转攻击阈值（第3轮开始检测）
THRESHOLD_DESC="统一阈值=0.1（标签翻转）"

# 无攻击模式检测阈值（仅用于分析）
NO_ATTACK_THRESHOLD="0.1"         # 参考阈值
# ===============================================

# warm-up轮数设置为3轮（无攻击模式优化）
WARMUP_ROUNDS=3
# Round索引从0开始，所以最后一轮暖机是 WARMUP_ROUNDS-1
WARMUP_ROUNDS_END=$((WARMUP_ROUNDS - 1))

# 根据攻击类型计算恶意客户端数量
if [ "$ATTACK_TYPE" = "no_attack" ]; then
    NUM_MALICIOUS=0
    MALICIOUS_DESC="0个（无攻击模式）"
    NUM_SELECTED_WARMUP=10  # 暖机期：10个良性
    NUM_SELECTED_NORMAL=20  # 正常期：20个良性
elif [ "$ATTACK_TYPE" = "noise_injection" ]; then
    NUM_MALICIOUS=10
    MALICIOUS_DESC="10个（第${WARMUP_ROUNDS}轮起，良性：恶意=1:1）"
    NUM_SELECTED_WARMUP=10  # 暖机期：10个良性
    NUM_SELECTED_NORMAL=20  # 正常期：20个（10良性+10恶意）
else
    NUM_MALICIOUS=10
    MALICIOUS_DESC="10个（第${WARMUP_ROUNDS}轮起，良性：恶意=1:1）"
    NUM_SELECTED_WARMUP=10  # 暖机期：10个良性
    NUM_SELECTED_NORMAL=20  # 正常期：20个（10良性+10恶意）
fi

# Non-IID参数映射（需要在Python输出之前准备）
if [ "$DATA_DISTRIBUTION" = "noniid" ]; then
    # 根据NONIID_CASE自动映射参数值（如果用户未手动设置）
    # 映射规则：NONIID_CASE -> (实际case编号, α, μ)
    # 重新组织：从低到高排序，1=轻度，2=中度，3=重度
    case $NONIID_CASE in
        1)
            ACTUAL_CASE=4  # case >= 4 使用Dirichlet分布
            DEFAULT_PROX_ALPHA="0.01"  # 极弱正则化，保证学习能力
            DEFAULT_BETA="0.8"
            ;;
        2)
            ACTUAL_CASE=5
            DEFAULT_PROX_ALPHA="0.1"  # 中等正则化
            DEFAULT_BETA="0.5"
            ;;
        3)
            ACTUAL_CASE=6
            DEFAULT_PROX_ALPHA="0.5"  # 强正则化（重度异构需要更强约束）
            DEFAULT_BETA="0.1"
            ;;
        *)
            ACTUAL_CASE=5
            DEFAULT_PROX_ALPHA="0.1"
            DEFAULT_BETA="0.5"
            ;;
    esac
    
    # 如果用户没有手动设置，使用自动映射的值
    if [ -z "$DATA_BETA" ]; then
        export DATA_BETA="$DEFAULT_BETA"
    fi
    
    # 只在使用FedProx时设置μ参数
    if [ "$USE_FEDPROX" = "1" ] && [ -z "$PROX_ALPHA" ]; then
        export PROX_ALPHA="$DEFAULT_PROX_ALPHA"
    fi
    
    # 导出实际的case编号给Python脚本
    export ACTUAL_NONIID_CASE=$ACTUAL_CASE
fi

# 检查Python环境
if ! command -v python &> /dev/null; then
    echo "❌ Python 未安装"
    exit 1
fi

# 运行测试（输出信息由Python脚本负责）

cd "$(dirname "$0")"

# 通过环境变量传递参数
export ATTACK_TYPE=$ATTACK_TYPE
export DATA_DISTRIBUTION=$DATA_DISTRIBUTION
export NONIID_CASE=$NONIID_CASE
export DATA_BETA=$DATA_BETA
export USE_FEDPROX=$USE_FEDPROX
export ENABLE_DEFENSE=$ENABLE_DEFENSE

# 只在 USE_FEDPROX=1 或 PROX_ALPHA 有值时才导出 PROX_ALPHA
if [ "$USE_FEDPROX" = "1" ] || [ -n "$PROX_ALPHA" ]; then
    export PROX_ALPHA=$PROX_ALPHA
fi
if [ -n "$RANDOM_SEED" ]; then
    export RANDOM_SEED=$RANDOM_SEED
fi

# 调试：显示传递给Python的环境变量（仅在需要时启用）
if [ "${DEBUG_ENV:-0}" = "1" ]; then
    echo "🔍 环境变量调试信息:"
    echo "   DATA_DISTRIBUTION=${DATA_DISTRIBUTION}"
    echo "   NONIID_CASE=${NONIID_CASE}"
    echo "   ACTUAL_NONIID_CASE=${ACTUAL_NONIID_CASE}"
    echo "   DATA_BETA=${DATA_BETA}"
    echo "   ATTACK_TYPE=${ATTACK_TYPE}"
    echo "   USE_FEDPROX=${USE_FEDPROX}"
    echo "   PROX_ALPHA=${PROX_ALPHA}"
    echo ""
fi

python test_independent_detectors_training.py \
    --dataset $DATASET \
    --model $MODEL \
    --num_users $NUM_USERS \
    --epochs $EPOCHS \
    --frac $FRAC \
    --local_ep $LOCAL_EP \
    --lr $LR

echo ""
echo "=========================================="
echo "测试完成！"
echo "=========================================="
echo ""
# 根据数据分布构建文件名后缀
if [ "$DATA_DISTRIBUTION" = "noniid" ]; then
    DISTRIBUTION_SUFFIX="noniid_case${NONIID_CASE}_beta${DATA_BETA}"
else
    DISTRIBUTION_SUFFIX="iid"
fi
echo "结果文件: independent_test_${MODEL}_${ATTACK_TYPE}_${DISTRIBUTION_SUFFIX}_<timestamp>.json"
echo "           (timestamp格式: YYYYMMDD_HHMMSS，自动生成)"
echo ""
echo "💡 切换模型和数据集:"
echo "   ResNet18 + CIFAR-10 (默认):"
echo "     ./run_independent_detector_test.sh"
echo ""
echo "   LeNet5 + MNIST:"
echo "     MODEL=lenet5 DATASET=mnist ./run_independent_detector_test.sh"
echo ""
echo "   ResNet20 + Fashion-MNIST:"
echo "     MODEL=resnet20 DATASET=fmnist ./run_independent_detector_test.sh"
echo ""
echo "   组合示例 (ResNet20 + Fashion-MNIST + 标签翻转攻击):"
echo "     MODEL=resnet20 DATASET=fmnist ATTACK_TYPE=label_flipping ./run_independent_detector_test.sh"
echo ""
echo "💡 切换攻击类型:"
echo "   数据投毒攻击:"
echo "     标签翻转: ATTACK_TYPE=label_flipping ./run_independent_detector_test.sh"
echo "     噪声注入: ATTACK_TYPE=noise_injection ./run_independent_detector_test.sh"
echo ""
echo "   模型投毒攻击（论文实现）:"
echo "     PoisonedFL:      ATTACK_TYPE=poisonedfl ./run_independent_detector_test.sh"
echo ""
echo "   基线:"
echo "     无攻击:   ATTACK_TYPE=no_attack ./run_independent_detector_test.sh"
echo ""
echo "💡 切换数据分布:"
echo "   IID:      DATA_DISTRIBUTION=iid ./run_independent_detector_test.sh"
echo "   Non-IID:  DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh"
echo ""
echo "💡 切换Non-IID强度 (数字越大越异构，α和μ自动匹配):"
echo "   轻度异构: NONIID_CASE=1 DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh  (α=0.8, μ=0.1)"
echo "   中度异构: NONIID_CASE=2 DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh  (α=0.5, μ=0.1, 默认)"
echo "   重度异构: NONIID_CASE=3 DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh  (α=0.1, μ=0.5)"
echo ""
echo "💡 组合使用:"
echo "   标签翻转 + 重度Non-IID:"
echo "     ATTACK_TYPE=label_flipping NONIID_CASE=3 DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh"
echo ""
echo "   噪声注入 + 中度Non-IID (当前默认):"
echo "     ATTACK_TYPE=noise_injection NONIID_CASE=2 DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh"
echo ""
echo "   ResNet20 + Fashion-MNIST + 标签翻转:"
echo "     MODEL=resnet20 DATASET=fmnist ATTACK_TYPE=label_flipping ./run_independent_detector_test.sh"
echo ""
echo "💡 手动覆盖自动配置（高级）:"
echo "   自定义α值: NONIID_CASE=1 DATA_BETA=0.7 DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh"
echo "   自定义μ值: NONIID_CASE=1 PROX_ALPHA=0.05 DATA_DISTRIBUTION=noniid ./run_independent_detector_test.sh"
echo ""
echo "💡 控制随机种子:"
echo "   使用随机种子（默认，每次不同）:"
echo "     ./run_independent_detector_test.sh"
echo ""
echo "   使用固定种子（结果可复现）:"
echo "     RANDOM_SEED=42 ./run_independent_detector_test.sh"
echo ""
echo "   重复实验（消除偶然性，自动生成不同时间戳）:"
echo "     for i in {1..5}; do"
echo "       echo \"实验 \$i/5\""
echo "       ./run_independent_detector_test.sh"
echo "       sleep 2  # 确保时间戳不同"
echo "     done"
echo ""

