# 电源、万用表和信号发生器

以下仅记录本地已验证工作流的命令，不推断其他固件也支持全部命令。此次 skill 的实机验收状态记录在仓库 README；离线测试不能替代设备验证。

## DP832A

每通道：`:APPL? CHn` 读电压/限流设置，`:OUTP? CHn` 读开关，`:OUTP:MODE? CHn` 读 CV/CC，`:MEAS:ALL? CHn` 读电压/电流/功率。
设定：`:APPL CHn,V,I`；输出：`:OUTP CHn,ON/OFF`；错误：`:SYST:ERR?`。

`supply-set` 先记录原值，再写入并检查错误、设置读回，最后按明确要求改变输出。它不会自动切断、自动恢复或关闭其他通道；出错会保留已完成动作，报告状态可能已部分改变，需先只读检查再决定恢复。电源面板值、输出端回读和 DUT 端电压分开。

## DM3058 / DM3058E

- 查询身份 `*IDN?`；当前功能 `:FUNCtion?`。
- DCV `:MEASure:VOLTage:DC?`；DCI `:MEASure:CURRent:DC?`。这些查询可能选择测量功能，所以不是身份发现阶段的安全探测命令。
- DM3058E 已有固件验证中未找到可用的功能/量程/速度 setter，不能套用 34401A 的 CONF/SENS 命令。量程/Slow 等由面板确认。不同 command set 必须重新核对。
- 有限读数不代表刷新正常。连续完全相同值标记待检查；不能自动判坏，也不能通过切电源制造验证信号。绝对值 >=1e15 的已知超量程哨兵和非有限值不参与平均。
- µA/mA 显示转换以 A 原始单位为基础；保留每个原始字符串，样本数、均值和极值。

## DG1022Z

本工具 status 支持输出/函数/频率/幅值/偏置查询。型号必须为 DG1022Z；DG1022、DG1022U 不复用限值。

已有 DG1022Z 验证指令：

```
:OUTPut1:STATe?                   # 1/2 通道
:SOURce1:FUNCtion?
:SOURce1:FREQuency?
:SOURce1:VOLTage?
:SOURce1:VOLTage:OFFSet?
:OUTPut1:LOAD?
```

写入形式为 `:SOURce1:FUNCtion SIN`、`:SOURce1:FREQuency 1000`、`:SOURce1:VOLTage 1`、`:SOURce1:VOLTage:OFFSet 1.65`、`:OUTPut1:LOAD INF`、`:OUTPut1:STATe ON/OFF`。执行前必须根据当前接线明确可承受峰值/偏置/频率/负载，先输出关闭、设置与读回、最后按授权开启；关闭正在使用的输出也属于改变现状。

幅值显示取决于 50 Ω / 高阻负载设置，不能把显示值直接等同接到高阻输入后的实际电压。连接到芯片时检查 offset±Vpp/2 的上下限、地参考及引脚是否也被配置成输出。只连接仪器的任务不包含打开波形输出。
