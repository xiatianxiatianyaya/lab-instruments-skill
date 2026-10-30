---
name: lab-instruments
description: Connect and coordinate laboratory oscilloscopes, DC supplies, multimeters, signal generators and debug probes on Windows via VISA/USB-TMC/LAN and J-Link/CMSIS-DAP. Use for bench discovery, instrument status, DC voltage/current acquisition, waveform export and authorized supply changes; do not infer chip register maps or flash firmware from this skill.
---

# 实验室多仪器连接与采集

统一入口为 `scripts/bench.py`。支持 RIGOL DS1202Z-E / DHO814、DP832A、DM3058 / DM3058E、DG1022Z；J-Link / CMSIS-DAP 只做探针枚举。其他型号可以查询身份，不能套用这些型号的指令。

## 先识别，再操作

1. 用已安装依赖的 Python；没有依赖时建立独立虚拟环境并安装 `requirements.txt`。Windows USB-TMC 优先使用已有厂商 VISA；PyVISA 本身不包含 VISA 驱动。详见 [连接与故障排查](references/connections.md)。
2. `python scripts/bench.py discover --out logs/discovery.json`：仅枚举 USB/TCPIP INSTR，不探测串口，不发送复位、清状态、测量档位切换或输出命令。`--idn` 才查询身份；`--probes` 只枚举调试探针，不连接内核。无自动发现的 LAN 仪器使用用户提供的 `--resource`，不要扫网段。
3. 指定精确 VISA resource 后运行 `status`。每次核对身份；同型号多台不能按“第一个资源”选取。可用 `--serial` 增加序列号校验。接线变更后重新核对通道映射。
4. 根据用户任务选择下面操作。此前已确认且未变化的接线、权限可复用；不要机械地要求再次确认。打印正在测试的项目、供电、测量点和预期输出。

## 操作入口

以下命令的 `RESOURCE` 必须替换成刚识别的地址；日志路径不写进共享仓库。

```powershell
python scripts/bench.py discover --idn --probes --out logs/discovery.json
python scripts/bench.py status --resource RESOURCE --out logs/status.json
python scripts/bench.py dmm-read --resource RESOURCE --function DCI --count 20 --interval 0.5 --out captures/current
python scripts/bench.py dmm-read --resource RESOURCE --function DCI --count 20 --interval 0.5 --out captures/current --apply
python scripts/bench.py scope-export --resource RESOURCE --channel 1 --out captures/ch1 --apply
python scripts/bench.py supply-set --resource RESOURCE --channel 1 --voltage 3.3 --current 0.1 --max-voltage 5 --max-current 0.1 --output keep --out logs/power.json
```

- `dmm-read`、`scope-export`、`supply-set` 默认只打印操作计划；`--apply` 执行。该开关是防误触执行机制，不替代用户对实际操作的授权。
- `dmm-read` 的测量查询可能改变档位。先确认红表笔插孔及串联/并联接法：电流串联，电压并联。**电流回路不能直接切成电压测量；电源两端不能切到电流档。** 本工具不猜测远程量程/速度指令。保留用户接受的自动量程，记录量程未知及负担电压影响。
- `scope-export` 导出已停止采集的当前记录；运行中会拒绝，除非明确指定 `--stop`。它不自动运行、单次触发或关掉其他通道。输出 CSV、SVG 与元数据；不能把缓存波形说成刚触发的新波形。见 [示波器](references/oscilloscopes.md)。
- `supply-set` 仅支持 DP832A 单路。先指定允许电压/电流边界，确认供电来源、通道及是否存在其他供电。默认保持输出状态，只有显式 `--output on/off` 改变开关。验证设置值与输出状态；终端读数并非芯片端独立实测值。多路跟踪/串并联模式需先解除或使用专门方案，不能把本命令当同步扫压。
- DG1022Z 本入口支持状态查询；参数写入与输出开启按 [信号发生器](references/supply-dmm-generator.md) 的命令依据和接线检查执行，不能把其他 DG 型号当 DG1022Z。
- J-Link/DAP 发现不等于目标芯片连通。固件、复位、寄存器或选项字节任务应读取项目手册和适用调试技能；本 skill 不自带任何芯片地址、解锁算法、固件或擦除动作。

## 多设备协同及数据质量

- 一台设备一个会话，顺序请求/响应。不同设备的独立只读查询可并行，但电源变更、触发和采集有先后关系时必须顺序执行。不要用两个程序同时占用同一台仪器。
- 先记录状态/接线，再布置触发，确认已武装后才进行授权的刺激或复位。软件顺序采样不等于硬件同步；纳秒延迟需同次采集、两通道探头时差校正。
- 功耗采集按用户要求断开整根调试排线，防止反向供电及调试影响；只有确认正常执行待测程序时才接收数据。程序异常、复位、掉电、配置不符不能算有效测试点。
- DMM 持续相同读数不一定坏；若断电/输入改变后仍完全相同，则检查 HOLD、触发、缓存或刷新状态，不把旧数当新测量。无效数、超量程哨兵、NaN 和通信失败必须保留并标失败。
- 保存原始值、时间戳、型号/序列号/固件、单位、接线、供电位置、温度和前后状态。未确认条件写“未知”，实测、计算、设计值分开。用户手读数不标成自动平均或保证上限。
- 通信超时后停下当前序列，避免迟到回复错配；不要自动反复下发输出命令、清空错误队列、恢复出厂或擦除目标。可做一次有依据的连接重试；还不通就报告阻塞原因。

## 本地与共享

设备资源/序列号/接线可保存在 `bench.local.json`，结果放 `logs/`、`captures/`。这些均不随 GitHub 包提交。不得附带芯片设计文档、NVR/Flash 备份、测试数据、令牌或驱动 DLL。同步是用户本次授权的操作，不是运行此 skill 自动执行的行为。
