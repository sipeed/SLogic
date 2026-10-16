# 更新日志

SLogic 软件包（SLogicView、PulseView、AllLogic、ngscopeclient、sigrok-cli）的中文版发布说明，
内容与 [CHANGELOG.md](CHANGELOG.md) 对应。发布页面 <https://github.com/sipeed/SLogic/releases>
上依次展示英文与中文两部分；硬件支持、系统要求与安装方法请见 [README](README.md)。

## v2.3.2 — 2026-10-16

SLogic 2.3.2 是一个维护版本：修复 Windows 上的问题，并提高 SLogic32U3 的最低固件版本。系统要求、下载与安装方式不变，详见
[README](https://github.com/sipeed/SLogic#readme)。

> [!IMPORTANT]
> **SLogic32U3 现需要固件 S/N {{firmware.slogic32u3.min}} 或更新版本。** 该固件包含
> S/N 202610140927 的全部改进，并新增启动自动恢复：上电或复位后若采集通路未能正常启动，
> 分析仪会自动重新初始化，并在就绪后才开始采集。升级方法请参阅 SLogic Wiki（[中文]({{firmware.slogic32u3.update_guide.zh}}) · [English]({{firmware.slogic32u3.update_guide.en}})）。

### 修复

- **Windows：采集过程更安静、更省资源。** sigrok-cli、PulseView 和 SLogicView 在采集时
  不再反复输出 "WaitForMultipleObjectsEx failed" 信息，也不再因此占用 CPU。采集数据本身
  不受影响；AllLogic 和 ngscopeclient 不受此问题影响。

## v2.3.1 — 2026-10-16

SLogic 2.3.1 是一个维护版本：SLogic32U3 的采样时钟更加统一，ngscopeclient 的模拟（ADC）
支持得到改进。系统要求、下载与安装方式与 2.3.0 相同，详见
[README](https://github.com/sipeed/SLogic#readme)。

> [!IMPORTANT]
> **SLogic32U3 需要固件 S/N 202610140927 或更新版本**（与 2.3.0 相同）。
> 升级方法请参阅 SLogic Wiki（[中文](https://wiki.sipeed.com/hardware/zh/logic_analyzer/slogic32u3/Hardware_Specification.html#%E6%9B%B4%E6%96%B0%E5%9B%BA%E4%BB%B6) · [English](https://wiki.sipeed.com/hardware/en/logic_analyzer/slogic32u3/Hardware_Specification.html#Firmware-Update)）。

### 改进

- **SLogic32U3 采样时钟统一。** 5 至 800 MHz 的所有采样率现在都由分析仪的 800 MHz
  时钟产生，共用同一个时钟源；4ch@1400 MHz 仍使用其专用时钟。该改进适用于所有上位机。
- **ngscopeclient：模拟通道组（ADC）。**
  - Stream Browser 中新增 **ADC bit order（ADC 比特序）** 设置：*Auto*（真实信号下
    CH0 = MSB，与 ADC 模块的接线一致；内置测试图案下 CH0 = LSB）、*CH0 = MSB*、
    *CH0 = LSB*。
  - 模拟边沿触发现在只在所选边沿（Rising、Falling 或 Any）上触发，并内置迟滞，
    带噪声的信号也能稳定显示。
  - 通道组处于模拟模式时，采集使用 ADC 的 800 MHz 时钟，使采样与 ADC 保持同步；
    该模式下不提供 1400 MHz。

### 其他

- libsigrok 的 udev 规则已包含 SLogic32U3，便于打包 libsigrok 的发行版使用。

## v2.3.0 — 2026-10-14

SLogic 2.3.0 是 SLogic 软件包的首个正式版本，支持 Windows、macOS 和 Linux。
五款上位机共用同一套驱动核心，在所有支持的逻辑分析仪上均可实现满速流式采集、
硬件级速度的触发以及精确的采样点数。系统要求与安装方法请参阅
[README](https://github.com/sipeed/SLogic#readme)。

> [!IMPORTANT]
> **SLogic32U3 需要固件 S/N 202610140927 或更新版本。** 该固件在所有通道模式下
> 均能干净地开始和结束采集，请在使用 2.3.0 前完成升级。固件 S/N 显示在各上位机的
> 设备列表中（`[S/N: …]`），也可通过 `sigrok-cli -d sipeed-slogic-analyzer --scan` 查看。
> 升级方法请参阅 SLogic Wiki（[中文](https://wiki.sipeed.com/hardware/zh/logic_analyzer/slogic32u3/Hardware_Specification.html#%E6%9B%B4%E6%96%B0%E5%9B%BA%E4%BB%B6) · [English](https://wiki.sipeed.com/hardware/en/logic_analyzer/slogic32u3/Hardware_Specification.html#Firmware-Update)）。

### 下载

各应用与平台对应的文件见上方英文部分的 **Downloads** 表格：Windows 选择
`*-windows-x86_64.exe`，macOS（Apple Silicon）选择 `*-macos-arm64.dmg`
（sigrok-cli 为 `.zip`），Linux 选择 `*-linux-x86_64.AppImage`。
推荐使用 **SLogicView**。

### 支持的硬件

| 设备 | 最高采样率 | 状态 |
|---|---|---|
| SLogic32U3（10 Gbps） | 4ch 1400 MHz · 8ch 800 · 16ch 400 · 32ch 200 | ✅ 本版本已测试（固件 202610140927 或更新） |
| SLogic16U3（5 Gbps） | 4ch 800 MHz · 8ch 400 · 16ch 200 | ✅ 本版本已测试 |
| SLogic Combo 8（USB 2.0） | 2ch 160 MHz · 4ch 80 · 8ch 40 | 支持 |

设备名称会显示当前连接的 USB 链路，例如 `(10G) Sipeed SLogic32 U3`，可选采样率
也会随链路自动调整（SLogic32U3 接 5 Gbps 端口时：4ch 800 · 8ch 400 · 16ch 200 ·
32ch 100 MHz）。

### 主要特性

- **全平台满速采集。** SLogic32U3 在 Windows、macOS 和 Linux 上均可持续跑满
  800 MB/s 的 USB 带宽（8ch@800 MHz 至 32ch@200 MHz，以及 4ch@1400 MHz），
  支持定长采集与连续采集。
- **所有上位机共用一套驱动核心。** 采集、触发、采样计数与异常恢复只实现一次、
  统一共享，五款上位机行为一致，改进也同步惠及所有应用。
- **硬件级速度的触发。** 每个通道可设低电平 / 高电平 / 上升沿 / 下降沿 / 任意边沿，
  在 4ch@1400 MHz 下也能实时跟上，并将触发点精确放在设定的预触发位置
  （默认 10%；sigrok-cli 中为 `captureratio`，AllLogic 中可用滑块在 0–90% 间调节）。
- **精确采集。** 每种通道模式都严格交付所请求的采样点数；连续采集
  （`sigrok-cli --continuous`、AllLogic 循环模式）会一直运行，直到手动停止。
- **自动识别链路。** 设备名称中显示当前 USB 链路（10G / 5G / USB 2.0），
  采样率列表随之自动调整。
- **操作响应迅速。** 停止操作立即生效（包括等待触发期间），设备重新连接后
  会被自动识别。
- **吞吐量报告。** 每次采集结束时输出一行摘要（`slogic-report v1`：速率、采样点数、
  触发位置）；日志级别 4（`-l 4`）下每 200 ms 显示一次实时速率。

### 从 2.x 预览版升级

- **SLogicView：** 界面文字放大到 14 px，面板按钮更大；添加解码器时自动打开
  协议解码器面板；重新连接后设备设置保持同步；运行 / 停止更加流畅，等待触发时
  也能随时停止。
- **AllLogic：** 新增触发功能，触发位置可在 0–90% 间调节；4 通道数据处理速度
  提升约 3.8 倍。
- **ngscopeclient：** 4 通道波形显示准确，超大深度采集依然流畅。
- **sigrok-cli：** 4 通道模式下任意长度都能得到精确的采样点数。

### 说明

- 触发条件按通道设置，各通道之间为"与"关系。多级触发序列（DSView 的高级触发模式）
  不在本版本范围内。
- 如需 SLogic32U3 的完整采样率，请将其直接连接到 10 Gbps USB 端口，并使用支持
  10 Gbps 的线缆。
- 使用固件 202512261505 的 SLogic16U3：4 通道 800 MHz 采集的开头可能出现少量
  重复样本。新版固件正在准备中，其他模式不受影响。

### 质量保证

每个发布版本都在真实硬件上通过了我们在 Windows、macOS 和 Linux 上的自动化测试，
覆盖各通道模式下的吞吐量、精确采样点数、连续采集、触发位置、反复打开 / 采集 /
关闭以及协议解码：

| 设备 | Linux | macOS | Windows |
|---|---|---|---|
| SLogic32U3 @ 10 Gbps | ✅ | ✅ | ✅ |
| SLogic32U3 @ 5 Gbps | ✅ | ✅ | ✅ |
| SLogic16U3 @ 5 Gbps | ✅ | ✅ | ✅ |

## 预览版（2.0.0 – 2.2.0）

2.0.0、2.1.0 和 2.2.0 是一体化软件包的预览版。其中的改进，包括 Windows 满速采集、
ngscopeclient 可调阈值、用于自动化的 sigrok-cli 插件以及大深度采集性能等，
均已包含在 2.3.0 中。
