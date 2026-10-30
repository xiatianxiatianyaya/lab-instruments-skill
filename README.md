# Lab Instruments Skill

面向 Codex 的实验室仪器联控技能：统一发现与记录设备，按明确接线执行采集，保存原始结果和通信日志。

| 设备 | 已实现入口 |
|---|---|
| RIGOL DS1202Z-E、DHO814 | 身份、通道状态、停止记录的 RAW/BYTE 波形 CSV + SVG 导出 |
| RIGOL DP832A | 三路状态查询、带 DUT 电压/电流边界的单路设定与读回 |
| RIGOL DM3058 / DM3058E | 身份/功能查询、DCV/DCI 批量采集和统计 |
| RIGOL DG1022Z | 输出、负载、频率、幅值、偏置查询；写命令流程参考技能附录 |
| J-Link、CMSIS-DAP | 可选探针枚举；不连接/复位/下载目标 |

不支持的型号仅识别身份，不发送型号专属命令。串口与裸 TCP socket 不自动探测。供电、电流表切换和输出动作不在发现命令中执行。

## 安装

复制本仓库 `lab-instruments` 目录到 `$CODEX_HOME/skills/`；未设置 CODEX_HOME 时放到 `~/.codex/skills/`。在 Codex 中使用 `$lab-instruments`，或自然语言要求识别/连接测试仪器。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r lab-instruments/requirements.txt
.\.venv\Scripts\python.exe lab-instruments/scripts/bench.py discover --idn --probes --out logs/discovery.json
```

USB-TMC 还需要已有的厂商 VISA 驱动。J-Link 枚举需要 SEGGER 软件；可选的 DAP 枚举需另装 `pyocd`。驱动、DLL 与 Python 环境不随仓库分发。

先看 `lab-instruments/SKILL.md` 中的命令示例。写入/采集操作默认为 dry-run，添加 `--apply` 才执行。配置模型/串号与接线必须对应当前设备；日志中的未知条件不补猜。

## 验证与限制

2026-10-30 本机发现测试：系统 VISA 后端成功加载；没有发现 USB/TCPIP 仪器，三个串口资源被跳过；成功枚举一台 J-Link。未安装 pyocd，因此未验证 DAP 枚举。此次没有切换仪器输出，也没有测量或修改 DUT。

设备命令依据来自既有控制脚本和设备验证记录；本次无在线仪器，状态/波形/电源设置/万用表读数不能声称已经重新完成实机验收。重新接入设备后，先只读识别，再按接线执行对应项目。

离线回归覆盖 dry-run 不接硬件、型号/电压边界、输出保持、读回不符禁止开启输出、超量程拒绝、波形单位换算、截断数据拒绝、超时停止、部分结果保留、同设备会话锁。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 共享范围

仓库仅含通用技能和控制代码，不含芯片手册、测试数据、程序/校准区备份、仪器序列号、账号凭据。`*.local.json`、`logs/`、`captures/` 被忽略；共享前仍须检查待提交列表。GitHub 同步由用户指定的账号执行，技能不会自行同步数据。
