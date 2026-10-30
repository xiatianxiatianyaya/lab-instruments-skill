# 示波器：DS1202Z-E / DHO814

## 已有命令依据

DS1202Z-E 的命令来自此前使用并验证的 DS1000Z-E 编程指南工作流：
https://www.rigol.com/dam/global/downloads/brochures/en/program-guide/oscilloscopes/DS1000ZE_ProgrammingGuide_EN.pdf

DHO814 的命令来自已有 DHO814 USB 采集工具与设备验证；其中固件 00.01.05 使用 `:TRIG:SWE SING` 后接 `:RUN` 武装单次采集，不能只因发送了 `:SING` 就判定已武装。这不是所有型号通用约定。

只读状态：`*IDN?`、`:TRIG:STAT?`、`:TIM:SCAL?`、`:ACQ:MDEP?`、`:CHANn:DISP? / PROB? / SCAL? / OFFS? / COUP?`。
波形：`:WAV:SOUR CHANn`、`:WAV:MODE RAW`、`:WAV:FORM BYTE`、`:WAV:PRE?`、`:WAV:STAR`、`:WAV:STOP`、`:WAV:DATA?`。

## 导出边界

本入口只导出 RAW/BYTE、最多 250000 点；深存储更长时明确拒绝，不能悄悄截断。下载分块、校验数量，保存原始 byte 码，不能把数据当 ASCII 解析。

十项 preamble：format,type,points,count,xincrement,xorigin,xreference,yincrement,yorigin,yreference。

```
t[i] = (i - xreference) * xincrement + xorigin
v[i] = (raw[i] - yorigin - yreference) * yincrement
```

按仪器返回比例换算，不再额外乘一次 10×。物理探头倍率必须与通道设置一致。接地夹与保护地相通时只接相容的地节点。

`scope-export --apply` 需要 STOP；`--stop` 才主动冻结当前记录。它保留通道开关、量程、偏置和采样设置；会改变波形读取源/格式/模式/窗口，并且不自动恢复运行，结果里记录这些改变。导出同次多通道记录时先停止一次，依次导出且中间不 RUN。

要测启动/边沿事件，另行配置与读回触发，并确认 WAIT/RUN 后让用户或授权接口触发。STOP 可能是原先停止，不能作为新触发证据。TD/T'D 需要按型号解释。微小 DAC 码差、0.5 LSB 建立时间与 FFT 动态指标必须评估仪器噪声/带宽/分辨率；不能只靠显示小数位数保证精度。
