# SLogic16U3 / 32U3 回归测试清单

**范围**:SLogic16U3 与 SLogic32U3(脚本按 `--scan` **自动识别型号**并选对应档位/标准),
sigrok-cli / libsigrok 链(SLogicView / PulseView 同一条驱动,一并覆盖),三平台 Linux / macOS /
Windows。每次固件或上位机更新后跑一遍,通过再发布。(文件名沿用 `-slogic32u3`,现已覆盖两款。)

**方式**:绝大部分由脚本 `build/bench/slogic_selftest.py` 自动完成(自动识别 16U3/32U3),三平台各跑一次;
少量人工补充。条目标注 **[脚本]**(自动)/ **[人工]**。

---

## 1. 规格与预期(判定依据)

| 项 | SLogic16U3 | SLogic32U3 |
|---|---|---|
| 通道 | 16 路 D0–D15 | 32 路 D0–D31 |
| 接口 / 运行态 PID | USB3 **5Gbps**,`359F:3031` | USB3 **10Gbps**,`359F:3032` |
| 通道档位 ↔ 最高采样率 | 4ch@800 · 8ch@400 · 16ch@200 MHz | 4ch@1400 · 8ch@800 · 16ch@400 · 32ch@200 MHz |
| 聚合标准(满速) | **400 MB/s**(原生 5G) | **800 MB/s**(10G;降到 5G 则总带宽封顶 400:4ch@800 · 8ch@400 · 16ch@200 · 32ch@100) |

> DFU 固件态为 USB2 FS,PID `359F:30F1`(采集驱动看不到,正常)。档位以 `--show` 为准,来源 `slogic/slogic*.c`。

**两款共用**:

| 项 | 规格 / 预期 |
|---|---|
| 数字阈值 | 单一全局比较器,`voltage_threshold` 是「低-高」对(单阈值写 `1.7-1.7`),0–6 V |
| 采集模式 | `Normal`(实采)/ `USB connection test`(裸链路冲刺,max_speed)/ `Emulation`(结构化图案) |
| 关键语义 | `--config` 多项用**冒号 `:` 分隔**(不是逗号)。`logic_channels=N` 选档位 + 自动使能 D0..D(N-1) + 重算最高速率,故写在 `samplerate` 前;超限速率被**截断并告警**。触发匹配 `0 1 r f e`。 |
| 预期性能 | Normal/Emulation 各档位**实测平均速率 ≥ 期望的 90%**(仅"收齐"不算满速——驱动按主机节奏排空;驱动 avg 从**首字节**起计,已排除冷启动/下电唤醒,首次冷采也显示真实速率);USB-test(max_speed)裸链路 **≥ 标准**(32U3 实测 ≈900–986,16U3 受设备聚合上限 ≈410) |

---

## 2. 三平台执行:下载 sigrok-cli → 跑脚本

每台机器按三步走,各出一次 PASS/FAIL + 可归档记录。脚本 `build/bench/slogic_selftest.py`
是**单文件、零依赖**(仅标准库),可直接从仓库跑,或把这一个文件拷到被测机旁再跑。

### 步骤 1 — 下载本平台的 sigrok-cli

到 Releases 页 <https://github.com/sipeed/SLogic/releases> 选对应版本,下载本平台的 **sigrok-cli** 资产:

| 平台 | 下载资产 | 落地处理 | `--sigrok-cli` 指向 |
|---|---|---|---|
| Linux | `sigrok-cli-SLogic-<ver>-linux-x86_64.AppImage` | `chmod +x` | 该 AppImage |
| Windows | `sigrok-cli-SLogic-<ver>-windows-x86_64.exe` | 无(单文件) | 该 `.exe` |
| macOS | `sigrok-cli-SLogic-<ver>-macos-arm64.zip` | 解压 | 解压目录内 `sigrok-cli-SLogic-macos-arm64/sigrok-cli` |

> macOS 首次运行若被 Gatekeeper 拦:`xattr -dr com.apple.quarantine <解压目录>` 放行(内部测试即可)。

### 步骤 2 — 插上设备(SLogic16U3 或 32U3)

直连机身 USB-3 口、**别过 hub / 用好线**。32U3 需稳在 **10G**(落到 5G 则按 400 MB/s 总带宽封顶,脚本自动换算档位);16U3 原生
**5G**(聚合 400 即满速)。脚本从 `--scan` 自动识别型号。

### 步骤 3 — 跑脚本

```sh
python3 slogic_selftest.py --sigrok-cli <步骤1的路径> \
    [--golden-dir <黄金目录>] [--usb-speed 10G|5G] [--min-rate-pct 90]
```

- Windows 用 `py -3 slogic_selftest.py ...`,路径写 `C:\...\sigrok-cli-SLogic-<ver>-windows-x86_64.exe`。
- 从仓库跑则路径为 `build/bench/slogic_selftest.py`。
- 无需信号源:采集用板载 Emulation/USB-test 图案写空设备、读驱动 `-l 4` 实测速率;解码用预录黄金 `.sr`。

脚本一键跑完下面所有 **[脚本]** 项,全 PASS 退出 0、任一 FAIL 退出非零。**输出直接对应本清单**:每行前缀即下表 `#`
(如 `[PASS] 3.1 rate-32ch@200MHz-Emulation …`)。Windows 探不到链路时用 `--usb-speed` 指定。运行结尾打印
**溯源信息 + 一行可粘贴到 §5 签收表的记录**,执行即归档。

---

## 3. 脚本自动项(三平台各跑一次,全自动)

> `#` 与脚本输出行前缀一一对应;本节全部由脚本完成,无需人工、无需信号源。3.1 脚本展开为 8 行({Emulation,Normal}×4 档)。

| # | 操作 / 命令 | 预期 | 结果 |
|---|---|---|---|
| 1.1 | `--version` | 三库版本齐全;打印被测 CLI 的 sha256 | |
| 1.2 | `-L` | 列出 `sipeed-slogic-analyzer` 驱动 | |
| 1.3 | `--protocol-decoders uart --show` | UART decoder 能加载 | |
| 2.1 | `-d ... --scan`(`-l 4`) | 识别 1 台 SLogic16U3/32U3,打印型号 + VID:PID + S/N | |
| 2.2 | `-d ... --show` | 列出 D0..D31、采样率表、config 键 | |
| 2.3 | 链路速率(Linux sysfs / macOS ioreg 自动探测) | 运行态 10G;**Windows 探不到**→显示 `unknown` 默认按 10G,见 §4 H2 | |
| 3.1 | 各档位 × {Emulation,Normal} 实测速率(写 `/dev/null`,读驱动 `-l 4` avg) | 每行 avg ≥ 期望的 90%、100% 收齐 | |
| 3.2 | maxspeed:`pattern=USB connection test` 裸链路冲刺 | avg ≥ 标准(常大幅超标,10G≈986) | |
| 3.3 | 超限采样率(按型号:32U3 `32ch@1400m` / 16U3 `16ch@400m`) | 速率被截到档位上限并告警(档位联动) | |
| 3.4 | stress:20 次 open/采集/close 循环(`--stress-iters` 可调) | 全成功,无崩/无泄漏 | |
| 4.1 | 解码黄金 `.sr`(`--golden-dir`:UART,按需 SPI/I²C) | 与黄金输出一致 | |

> macOS 首次运行 CLI 产物若被 Gatekeeper 拦,内部测试放行即可(非 GUI 签名范畴)。

### 说明:Windows 吞吐(历史问题,已解决)

早期 Windows 原生采集跑不满(16U3 ~390/400、32U3 被压),成因有三,现已逐一解决:

1. **libusb WinUSB 未开 RAW_IO** → 后端只保持 1 个 bulk-IN 在途,高速率吞吐受限。**2.1.0 起驱动启用 RAW_IO**。
2. **固件下电阈值过短(0.56s)** → 用例间空闲触发下电,每次采集先付 ~7.5ms 唤醒(500ms 用例 ≈98%)。**固件 lp6(SN 202610121551)起阈值提到 4.5s**。
3. **测速把冷启动唤醒算进去** → 均值偏低、首次冷采显示"不满速"。**驱动 avg 改为从首字节起计**,已排除冷启动/下电唤醒。

结论:够格主机(10G 口 + 好线)下 **32U3 满 800、16U3 满 400,无丢包**(实测 MRTIVO2)。弱机(USB 栈/端口差,如某些机器 ~445 封顶)可能仍受自身硬件所限;用 `--usb-speed` 指定实际链路,必要时以 Linux 为满速基准交叉验证。

---

## 4. 人工补充(集中一次做,非每次必做)

脚本已覆盖功能 / 性能 / 压力 / 黄金解码。下面只保留**必须人工**的项,按触发条件做,别每次全跑:

| # | 何时做 | 操作 | 预期 |
|---|---|---|---|
| H1 | **每次发布** | 抽验 SLogicView / PulseView 各开一次:扫描→采集→解码→退出 | 与脚本一致,正常退出、无崩 |
| H2 | Windows 且 2.3 探不到链路 | USBTreeView 等确认链路代数,脚本加 `--usb-speed 10G\|5G` 重跑 | 判定用对标准 |
| H3 | 固件/解码器动了**采集格式或解码** | 现场台架实采 UART/SPI/I²C/PWM 并解码;正确后刷新黄金 `.sr` 入库(供 4.1 复用) | 解出预期内容、0 warning |
| H4 | 固件动了**阈值或触发** | 临界电平信号:`voltage_threshold` 设低/高各采一次;`--triggers D0=r` 再 `D0=f` | 0/1 判决随阈值变;触发落在对应边沿 |

> 黄金 `.sr` 夹具:`--golden-dir` 下每条放 `<名>.sr` + `<名>.args`(decode 参数)+ `<名>.expected`;在 Linux 上用真实信号采一次、确认正确后入库,三平台复用。

---

## 5. 签收

- [ ] 三平台 §3 脚本各跑一次均 PASS(型号自动识别;Windows 满速背景见上「说明」)。
- [ ] §4 人工项按触发条件完成(每次发布至少 H1)。
- [ ] 失败项已立 issue、修复、重跑。
- [ ] → 以上完成后才按 [release-process.md](release-process.md) 打 tag。

脚本结尾打印一行可直接粘贴到下表的记录(固件 / build / 操作人自填):

| 日期 | 固件 | 上位机 build | 平台 | 序列号 | 操作人 | 结论 |
|---|---|---|---|---|---|---|
| | | | | | | |
