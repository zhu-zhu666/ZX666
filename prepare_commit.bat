@echo off
REM 准备提交前的清理脚本 - 确保不提交大文件

echo ==========================================
echo 准备提交前的清理和检查
echo ==========================================
echo.

REM 1. 创建必要的目录
echo 📁 创建必要的目录...
if not exist "docs\archived" mkdir docs\archived
if not exist "results" mkdir results

REM 2. 移动Bug调试文档到归档
echo 📦 归档Bug调试文档...
if exist "BUG_FIX_SUMMARY.md" (
    move /Y "BUG_FIX_SUMMARY.md" "docs\archived\" >nul 2>&1
    echo   ✓ BUG_FIX_SUMMARY.md -^> docs/archived/
)

if exist "BUG_POISONEDFL_NO_EFFECT.md" (
    move /Y "BUG_POISONEDFL_NO_EFFECT.md" "docs\archived\" >nul 2>&1
    echo   ✓ BUG_POISONEDFL_NO_EFFECT.md -^> docs/archived/
)

if exist "CRITICAL_BUG_FIXED.md" (
    move /Y "CRITICAL_BUG_FIXED.md" "docs\archived\" >nul 2>&1
    echo   ✓ CRITICAL_BUG_FIXED.md -^> docs/archived/
)

REM 3. 移动实验结果到results目录
echo.
echo 📊 移动实验结果文件...
for %%f in (independent_test_*.json) do (
    if exist "%%f" (
        move /Y "%%f" "results\" >nul 2>&1
        echo   ✓ %%f -^> results/
    )
)

REM 4. 删除旧实验结果
echo.
echo 🗑️  删除旧实验结果...
if exist "independent_test_lenet5_poisonedfl_iid_20251110_*.json" (
    del /Q "independent_test_lenet5_poisonedfl_iid_20251110_*.json" 2>nul
    echo   ✓ 删除2025-11-10的IID实验
)
if exist "independent_test_lenet5_poisonedfl_noniid_case5_beta0.5_20251110_*.json" (
    del /Q "independent_test_lenet5_poisonedfl_noniid_case5_beta0.5_20251110_*.json" 2>nul
    echo   ✓ 删除2025-11-10的Non-IID实验
)

REM 5. 显示.gitignore状态
echo.
echo 🛡️  .gitignore 规则已更新：
echo   ✓ 数据集文件 (data/mnist/, *.pt, *.pth, etc.)
echo   ✓ 实验结果 (results/, *.json)
echo   ✓ 模型权重 (*.pt, *.pth, *.h5, etc.)
echo   ✓ 训练日志 (logs/, *.log)
echo.

REM 6. 显示目录结构
echo 📂 当前目录结构：
echo.
tree /F /A docs 2>nul | findstr /V "Volume Serial"
echo.
tree /F /A results 2>nul | findstr /V "Volume Serial"
echo.

echo ==========================================
echo ✅ 清理完成！
echo ==========================================
echo.
echo 📋 下一步：
echo    1. 运行: git status
echo    2. 检查没有大文件（数据集、实验结果）
echo    3. 运行: git add -A
echo    4. 运行: git commit -m "feat: 实现PoisonedFL攻击"
echo    5. 运行: git push origin feature/add_multi_round_consistency_attack
echo.
pause
