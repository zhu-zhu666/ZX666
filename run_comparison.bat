@echo off
REM TEE-FL vs FLTrust vs FedAvg 对比实验运行脚本

echo ==========================================
echo 防御机制对比实验
echo ==========================================
echo.

echo 选择实验场景:
echo.
echo 1. 无攻击 (Baseline)
echo 2. PoisonedFL攻击, 20%%恶意客户端
echo 3. PoisonedFL攻击, 40%%恶意客户端
echo 4. PoisonedFL攻击, 60%%恶意客户端
echo 5. Label Flipping攻击, 40%%恶意客户端
echo 6. 运行所有场景 (完整对比)
echo.

set /p choice="请输入选项 (1-6): "

if "%choice%"=="1" goto scenario1
if "%choice%"=="2" goto scenario2
if "%choice%"=="3" goto scenario3
if "%choice%"=="4" goto scenario4
if "%choice%"=="5" goto scenario5
if "%choice%"=="6" goto all_scenarios
goto invalid

:scenario1
echo.
echo [运行] 场景1: 无攻击 (Baseline)
python test_defense_comparison.py ^
    --dataset mnist ^
    --model lenet ^
    --num_users 100 ^
    --epochs 20 ^
    --frac 0.1 ^
    --local_ep 2 ^
    --local_bs 10 ^
    --lr 0.01 ^
    --iid 1 ^
    --attack_type none ^
    --malicious_ratio 0.0 ^
    --gpu 0
goto end

:scenario2
echo.
echo [运行] 场景2: PoisonedFL攻击, 20%%恶意客户端
python test_defense_comparison.py ^
    --dataset mnist ^
    --model lenet ^
    --num_users 100 ^
    --epochs 20 ^
    --frac 0.1 ^
    --local_ep 2 ^
    --local_bs 10 ^
    --lr 0.01 ^
    --iid 1 ^
    --attack_type poisonedfl ^
    --malicious_ratio 0.2 ^
    --gpu 0
goto end

:scenario3
echo.
echo [运行] 场景3: PoisonedFL攻击, 40%%恶意客户端
python test_defense_comparison.py ^
    --dataset mnist ^
    --model lenet ^
    --num_users 100 ^
    --epochs 20 ^
    --frac 0.1 ^
    --local_ep 2 ^
    --local_bs 10 ^
    --lr 0.01 ^
    --iid 1 ^
    --attack_type poisonedfl ^
    --malicious_ratio 0.4 ^
    --gpu 0
goto end

:scenario4
echo.
echo [运行] 场景4: PoisonedFL攻击, 60%%恶意客户端
python test_defense_comparison.py ^
    --dataset mnist ^
    --model lenet ^
    --num_users 100 ^
    --epochs 20 ^
    --frac 0.1 ^
    --local_ep 2 ^
    --local_bs 10 ^
    --lr 0.01 ^
    --iid 1 ^
    --attack_type poisonedfl ^
    --malicious_ratio 0.6 ^
    --gpu 0
goto end

:scenario5
echo.
echo [运行] 场景5: Label Flipping攻击, 40%%恶意客户端
python test_defense_comparison.py ^
    --dataset mnist ^
    --model lenet ^
    --num_users 100 ^
    --epochs 20 ^
    --frac 0.1 ^
    --local_ep 2 ^
    --local_bs 10 ^
    --lr 0.01 ^
    --iid 1 ^
    --attack_type label_flipping ^
    --malicious_ratio 0.4 ^
    --gpu 0
goto end

:all_scenarios
echo.
echo [运行] 所有场景 - 这将需要较长时间...
echo.

echo ==========================================
echo 场景1: 无攻击
echo ==========================================
python test_defense_comparison.py --dataset mnist --model lenet --num_users 100 --epochs 20 --frac 0.1 --local_ep 2 --local_bs 10 --lr 0.01 --iid 1 --attack_type none --malicious_ratio 0.0 --gpu 0
echo.

echo ==========================================
echo 场景2: PoisonedFL 20%%
echo ==========================================
python test_defense_comparison.py --dataset mnist --model lenet --num_users 100 --epochs 20 --frac 0.1 --local_ep 2 --local_bs 10 --lr 0.01 --iid 1 --attack_type poisonedfl --malicious_ratio 0.2 --gpu 0
echo.

echo ==========================================
echo 场景3: PoisonedFL 40%%
echo ==========================================
python test_defense_comparison.py --dataset mnist --model lenet --num_users 100 --epochs 20 --frac 0.1 --local_ep 2 --local_bs 10 --lr 0.01 --iid 1 --attack_type poisonedfl --malicious_ratio 0.4 --gpu 0
echo.

echo ==========================================
echo 场景4: PoisonedFL 60%%
echo ==========================================
python test_defense_comparison.py --dataset mnist --model lenet --num_users 100 --epochs 20 --frac 0.1 --local_ep 2 --local_bs 10 --lr 0.01 --iid 1 --attack_type poisonedfl --malicious_ratio 0.6 --gpu 0
echo.

echo ==========================================
echo 场景5: Label Flipping 40%%
echo ==========================================
python test_defense_comparison.py --dataset mnist --model lenet --num_users 100 --epochs 20 --frac 0.1 --local_ep 2 --local_bs 10 --lr 0.01 --iid 1 --attack_type label_flipping --malicious_ratio 0.4 --gpu 0
echo.

echo ==========================================
echo 所有场景运行完成！
echo ==========================================
goto end

:invalid
echo.
echo 无效选项，请重新运行脚本
goto end

:end
echo.
echo 实验完成！结果已保存到 results/defense_comparison/
echo.
pause
