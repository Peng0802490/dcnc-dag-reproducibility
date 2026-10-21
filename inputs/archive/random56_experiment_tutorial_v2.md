# random5/random6 DCNC-DAG 仿真流程

## 1. 文件放置

在服务器代码根目录执行：

```bash
cd ~/dcnc_dag_py3
conda activate dcnc_dag
```

将 6 个 DAG 文件放入代码的 DAG 目录：

```bash
cp random5_1.json random5_2.json random5_3.json DAG/
cp random6_1.json random6_2.json random6_3.json DAG/
```

将本次生成的配置文件放入原 config 目录，例如：

```bash
cp config_random5_Milan.json config_random5_Random.json config_random5_Roofnet38.json config_random5_FlockLab.json configs/
cp config_random6_Milan.json config_random6_Random.json config_random6_Roofnet38.json config_random6_FlockLab.json configs/
```

如果配置目录不是 `configs/`，先定位原 random3/random4 config：

```bash
find . -name 'config_random4_Roofnet38.json' -o -name 'config_random3_Roofnet38.json'
```

## 2. 配置一致性检查

把 `validate_random56_configs.py` 放到代码根目录后执行：

```bash
python3 validate_random56_configs.py --config-dir configs --dag-dir DAG
```

该脚本检查 config 中的 `sources/sinks/allowed` 节点名是否与 DAG 文件中的 source/sink/node 集合一致。

## 3. 注册 case

定位原 case 映射：

```bash
grep -R "roofnet_random3\|flocklab_random3\|milan_random3\|random_random3" -n scripts src configs | head -100
```

新增 8 个 case：

```text
milan_random5    -> config_random5_Milan.json
random_random5   -> config_random5_Random.json
roofnet_random5  -> config_random5_Roofnet38.json
flocklab_random5 -> config_random5_FlockLab.json

milan_random6    -> config_random6_Milan.json
random_random6   -> config_random6_Random.json
roofnet_random6  -> config_random6_Roofnet38.json
flocklab_random6 -> config_random6_FlockLab.json
```

如果你的代码中 Roofnet case 使用 `roofnet38_random3` 或其他命名，应沿用原项目命名，只替换 config 文件名。

## 4. DynVMP 环境变量

Exact 策略需要 DynVMP bridge：

```bash
export DCNC_DYNVMP_CMD="$(pwd)/workspace/dcnc_dynvmp/run_dynvmp_bridge.sh"
chmod +x "$DCNC_DYNVMP_CMD"
test -x "$DCNC_DYNVMP_CMD" && echo "DynVMP bridge OK"
```

## 5. Smoke test

先跑 heuristic，检查 config、DAG 和 case 注册是否正确：

```bash
for case in \
  milan_random5 random_random5 roofnet_random5 flocklab_random5 \
  milan_random6 random_random6 roofnet_random6 flocklab_random6
do
  echo "=== heuristic smoke: $case ==="
  PYTHONPATH=src python scripts/run_wireless_benchmark_experiments.py \
    --case "$case" \
    --slots 50 \
    --seed-start 0 \
    --seeds 1 \
    --rate 0.01 \
    --policies DCNC-DAG \
    --dcnc-solver greedy \
    --fixed-k 1 \
    --interference-model primary \
    --progress-every 10 \
    --output-dir "results_paper_edge/random56_smoke/heuristic/$case"
done
```

再跑 exact smoke：

```bash
for case in \
  milan_random5 random_random5 roofnet_random5 flocklab_random5 \
  milan_random6 random_random6 roofnet_random6 flocklab_random6
do
  echo "=== exact smoke: $case ==="
  PYTHONPATH=src python scripts/run_wireless_benchmark_experiments.py \
    --case "$case" \
    --slots 20 \
    --seed-start 0 \
    --seeds 1 \
    --rate 0.01 \
    --policies DCNC-DAG \
    --dcnc-solver dynvmp_bridge \
    --dynvmp-cmd "$DCNC_DYNVMP_CMD" \
    --fixed-k 1 \
    --interference-model primary \
    --progress-every 5 \
    --output-dir "results_paper_edge/random56_smoke/exact/$case"
done
```

## 6. Pilot 阶段

生成 2000 slot、seed0、全策略 pilot 表：

```bash
python3 make_random56_run_tables.py \
  --out Random56_Pilot_2000slot_Seed0_Run_Table.csv \
  --stage random56_pilot \
  --slots 2000 \
  --seed-start 0 \
  --seeds 1 \
  --rates "0.01,0.02,0.03,0.05,0.08,0.10,0.15,0.20,0.30,0.50,0.80,1.00" \
  --policies exact,heuristic,cts,random \
  --exact-ks 1
```

运行 pilot：

```bash
python3 tmux_csv_command_scheduler_fastfill_enterfix.py \
  'Random56_Pilot_2000slot_Seed0_Run_Table.csv' \
  --session 0 \
  --cmd-col command \
  --allow-all-panes \
  --initial-busy-policy wait \
  --idle-detection relaxed \
  --idle-checks 1 \
  --idle-check-interval 0 \
  --poll 0.5 \
  --status-interval 10 \
  --log-dir ./sched_logs_random56_pilot
```

## 7. Long-run 阶段

根据 pilot 曲线确定每个 case 的 arrival rate。不要直接照搬 random3/random4 的点。random5/random6 的 DAG 更大，拐点可能更靠左。

示例生成 8000 slot、seed1 正式表：

```bash
python3 make_random56_run_tables.py \
  --out Random56_AllPolicies_8000slot_Seed1_Run_Table.csv \
  --stage random56_longrun \
  --slots 8000 \
  --seed-start 1 \
  --seeds 1 \
  --rates "0.01,0.03,0.05,0.08,0.10,0.15,0.20,0.30" \
  --policies exact,heuristic,cts,random \
  --exact-ks 1
```

运行：

```bash
python3 tmux_csv_command_scheduler_fastfill_enterfix.py \
  'Random56_AllPolicies_8000slot_Seed1_Run_Table.csv' \
  --session 0 \
  --cmd-col command \
  --allow-all-panes \
  --initial-busy-policy wait \
  --idle-detection relaxed \
  --idle-checks 1 \
  --idle-check-interval 0 \
  --poll 0.5 \
  --status-interval 10 \
  --log-dir ./sched_logs_random56_longrun
```

## 8. 结果目录建议

```text
results_paper_edge/
├── random56_smoke/
├── random56_pilot/
└── random56_longrun/
```

调度器日志单独放：

```text
sched_logs_random56_pilot/
sched_logs_random56_longrun/
```
