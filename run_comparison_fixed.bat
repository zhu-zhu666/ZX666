@echo off
REM 修复后的对比实验运行脚本
REM 1. 已修复args.device
REM 2. 降低攻击强度2.0
REM 3. 添加warmup调试输出
REM 4. 增加local_ep到50

echo ==========================================
echo 🚀 运行修复后的防御对比实验
echo ==========================================
echo.
echo 修复内容:
echo   ✅ 1. 修复args.device缺失
echo   ✅ 2. 降低攻击强度: 5.0 → 2.0
echo   ✅ 3. 添加warmup调试输出
echo   ✅ 4. 增加本地训练: local_ep=50
echo.
echo 预期结果:
echo   - Warmup期(1-3轮): 准确率上升到90%+
echo   - 攻击期(4-10轮): FedAvg下降到70%
echo   - TEE-FL/FLTrust: 保持95%+
echo.
echo ==========================================

python test_defense_comparison.py ^
    --dataset mnist ^
    --model lenet ^
    --num_users 50 ^
    --epochs 10 ^
    --frac 0.2 ^
    --local_ep 50 ^
    --attack_type poisonedfl ^
    --malicious_ratio 0.4 ^
    --iid 0

echo.
echo ==========================================
echo 实验完成！
echo ==========================================
pause
