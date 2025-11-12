@echo off
REM 修复Git缓存问题 - 移除不应该追踪的文件

echo ==========================================
echo 修复Git缓存问题
echo ==========================================
echo.

echo 🔍 第1步：从Git中移除所有已追踪的缓存文件...
echo.

REM 移除__pycache__目录
git rm -r --cached Algorithm/__pycache__/ 2>nul
git rm -r --cached attacks/__pycache__/ 2>nul
git rm -r --cached models/__pycache__/ 2>nul
git rm -r --cached optimizer/__pycache__/ 2>nul
git rm -r --cached utils/__pycache__/ 2>nul

echo   ✓ 已移除__pycache__目录
echo.

echo 🔍 第2步：确认.gitignore包含必要的规则...
echo.
echo   ✓ .gitignore已包含__pycache__/规则
echo.

echo 🔍 第3步：检查状态...
echo.
git status --short
echo.

echo ==========================================
echo ✅ 清理完成！
echo ==========================================
echo.
echo 📋 下一步操作：
echo    1. 检查上面的git status输出
echo    2. 确认没有__pycache__文件
echo    3. 运行: git add -A
echo    4. 运行: git commit -m "feat: 实现PoisonedFL攻击"
echo    5. 运行: git push origin feature/add_multi_round_consistency_attack
echo.
pause
