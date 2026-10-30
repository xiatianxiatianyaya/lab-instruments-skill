# 连接与故障排查

## Windows / VISA

- USB 接仪器的后面板 Device/USB-TMC 端口。前面板 USB Host 通常用于 U 盘，不能当成另一条远程连接。
- 首先复用已安装的 RIGOL/NI/Keysight VISA。`pyvisa.ResourceManager()` 使用系统 VISA；`--backend` 可指定已知 DLL 或已经配置的后端。
- `@py` 仅在 pyvisa-py 及相应 USB/网络依赖都安装后可用；不要为了换后端擅自替换设备驱动。
- LAN：使用已确认的 `TCPIP0::地址::INSTR` 或厂商公布资源；本脚本不支持任意 TCP socket SCPI，不扫描网络。
- 空列表与离线不同：空列表可能是驱动/后端问题。记录具体异常；设备管理器看到 USB-TMC 但 VISA 找不到时检查位数、驱动和进程占用。
- 超时只重试有明确原因的只读查询。发生协议错误时关闭会话，再由用户重新插 USB；不要将断电电源/重启 DUT 当无副作用连接修复。

## Debug probe

`discover --probes` 尝试 pylink 的 `connected_emulators()`；需本机合法安装 SEGGER J-Link DLL。CMSIS-DAP 枚举依赖可选的 pyocd，使用 `ConnectHelper.get_all_connected_probes()`，不调用 connect/open/session。

探针 USB 可见、VTref、SWD DP/AP 响应、CPUID、芯片 UID/ID 是不同层级；一项成功不能代替其他项。程序运行/停止、SWD 速度、供电、MCO、GPIO及引脚负载也应分开记录，不能用未知寄存器代替读 ID。

## 程序包

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r lab-instruments/requirements.txt
# 可选 DAP 枚举：
.\.venv\Scripts\python.exe -m pip install pyocd
.\.venv\Scripts\python.exe lab-instruments/scripts/bench.py discover --idn --probes --out logs/discovery.json
```

枚举失败不终止其他类型的发现；输出会区分驱动缺失、探针缺失与 VISA 设备错误。脚本自带进程锁约束自身调用，但不能阻止第三方 GUI/脚本占用同一仪器。
