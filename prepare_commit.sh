#!/bin/bash
# 准备提交前的清理脚本 - 确保不提交大文件

echo "=========================================="
echo "准备提交前的清理和检查"
echo "=========================================="
echo ""

# 1. 创建必要的目录
echo "📁 创建必要的目录..."
mkdir -p docs/archived
mkdir -p results

# 2. 移动Bug调试文档到归档
echo "📦 归档Bug调试文档..."
if [ -f "BUG_FIX_SUMMARY.md" ]; then
    git mv BUG_FIX_SUMMARY.md docs/archived/ 2>/dev/null || mv BUG_FIX_SUMMARY.md docs/archived/
    echo "  ✓ BUG_FIX_SUMMARY.md → docs/archived/"
fi

if [ -f "BUG_POISONEDFL_NO_EFFECT.md" ]; then
    git mv BUG_POISONEDFL_NO_EFFECT.md docs/archived/ 2>/dev/null || mv BUG_POISONEDFL_NO_EFFECT.md docs/archived/
    echo "  ✓ BUG_POISONEDFL_NO_EFFECT.md → docs/archived/"
fi

if [ -f "CRITICAL_BUG_FIXED.md" ]; then
    git mv CRITICAL_BUG_FIXED.md docs/archived/ 2>/dev/null || mv CRITICAL_BUG_FIXED.md docs/archived/
    echo "  ✓ CRITICAL_BUG_FIXED.md → docs/archived/"
fi

# 3. 移动实验结果到results目录
echo ""
echo "📊 移动实验结果文件..."
for file in independent_test_*.json; do
    if [ -f "$file" ]; then
        mv "$file" results/
        echo "  ✓ $file → results/"
    fi
done

# 4. 检查是否有大文件将被提交
echo ""
echo "🔍 检查潜在的大文件..."
echo ""

check_large_files() {
    local file=$1
    local size=$(du -sh "$file" 2>/dev/null | cut -f1)
    echo "  ⚠️  $file ($size) - 将被忽略"
}

# 检查数据集目录
if [ -d "data/mnist" ] && [ "$(ls -A data/mnist)" ]; then
    check_large_files "data/mnist/"
fi

# 检查实验结果
if [ -d "results" ] && [ "$(ls -A results)" ]; then
    echo "  ✓ results/ 目录 - 将被忽略"
fi

# 检查JSON文件
json_count=$(find . -maxdepth 1 -name "*.json" -type f 2>/dev/null | wc -l)
if [ $json_count -gt 0 ]; then
    echo "  ⚠️  发现 $json_count 个JSON文件在根目录 - 将被忽略"
fi

# 检查模型权重文件
model_files=$(find . -name "*.pt" -o -name "*.pth" -o -name "*.h5" 2>/dev/null | wc -l)
if [ $model_files -gt 0 ]; then
    echo "  ⚠️  发现 $model_files 个模型权重文件 - 将被忽略"
fi

# 5. 显示.gitignore状态
echo ""
echo "🛡️  .gitignore 规则已更新："
echo "  ✓ 数据集文件 (data/mnist/, *.pt, *.pth, etc.)"
echo "  ✓ 实验结果 (results/, *.json)"
echo "  ✓ 模型权重 (*.pt, *.pth, *.h5, etc.)"
echo "  ✓ 训练日志 (logs/, *.log)"
echo ""

# 6. 显示将要提交的文件类型统计
echo "📝 将要提交的文件类型："
echo ""
git add -A --dry-run 2>/dev/null | grep -E '\.(py|md|sh|txt|json)$' | awk '{print $2}' | sed 's/.*\.//' | sort | uniq -c | sort -rn || true

echo ""
echo "=========================================="
echo "✅ 清理完成！"
echo "=========================================="
echo ""
echo "📋 下一步："
echo "   1. 检查上面的文件列表"
echo "   2. 确认没有大文件（数据集、实验结果）"
echo "   3. 运行: git status 查看状态"
echo "   4. 运行: git add -A"
echo "   5. 运行: git commit -m 'feat: 实现PoisonedFL攻击'"
echo ""
