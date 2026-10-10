# SLogic32U3 回归测试清单

**范围**:SLogic32U3,sigrok-cli / libsigrok 链(SLogicView / PulseView 同一条驱动,一并覆盖),
三平台 Linux / macOS / Windows。每次固件或上位机更新后跑一遍,通过再发布。

**方式**:绝大部分由脚本 `build/bench/slogic_selftest.py` 自动完成,三平台各跑一次;少量人工补充。
条目标注 **[脚本]**(自动)/ **[人工]**。

---

## 1. 规格与预期(判定依据)

| 项 | 规格 / 预期 |
|---|---|
| 通道 | 32 路 D0–D31 |
| 枚举 | 运行态 **USB3 10Gbps(SuperSpeed)**,PID `359F:3032/3031/0300`;DFU 固件态为 USB2 FS,PID `359F:30F1`(采集驱动看不到,正常) |
| 通道档位 ↔ 最高采样率 | 4ch@1400 · 8ch@800 · 16ch@400 · 32ch@200 MHz(来源 `slogic/slogic32u3.c`;以 `--show` 为准) |
| 数字阈值 | 单一全局比较器,`voltage_threshold` 是「低-高」对(单阈值写 `1.7-1.7`),0–6 V |
| 采集模式 | `Normal`(实采)/ `USB connection test`(裸链路冲刺,max_speed)/ `Emulation`(结构化图案) |
| 关键语义 | `--config` 多项用**冒号 `:` 分隔**(不是逗号)。`logic_channels=N` 选档位 + 自动使能 D0..D(N-1) + 重算最高速率,故写在 `samplerate` 前;超限速率被**截断并告警**。触发匹配 `0 1 r f e`。 |
| 链路 → 标准 | 10G/SuperSpeed+ → 聚合标准 **800 MB/s**;5G/SuperSpeed → 采样率与标准**同时减半**(**400 MB/s**) |
| 预期性能 | Normal/Emulation 各档位**实测平均速率 ≥ 期望的 90%**(仅"收齐"不算满速——驱动会按主机节奏排空,所以要测真实速率);USB-test(max_speed)裸链路 **≥ 标准、常大幅超标**(10G 实测 ≈986 MB/s) |

---

## 2. 三平台执行:各跑一次脚本

每台插上 SLogic32U3,运行(Windows 用 `py -3`):

```sh
python3 build/bench/slogic_selftest.py --sigrok-cli <本平台的 sigrok-cli-SLogic 产物> \
    [--golden-dir <黄金目录>] [--usb-speed 10G|5G] [--min-rate-pct 90]
```

脚本自动跑完下面所有 **[脚本]** 项,一键 PASS/FAIL,失败非零退出。无需信号源(采集用 Emulation/USB-test
图案写 `/dev/null`、读驱动 `-l 4` 实测速率;解码用预录黄金 `.sr`)。`--sigrok-cli` 接可执行文件 / Windows
便携目录 / 已挂载的 macOS `.app`。

**输出直接对应本清单**:每行前缀即下表 `#`(如 `[PASS] 3.1 rate-32ch@200MHz-Emulation …`),
链路探不到时用 `--usb-speed` 指定。运行结尾打印**溯源信息 + 一行可粘贴到 §5 签收表的记录**,执行即归档。

---

## 3. 脚本自动项(三平台各跑一次,全自动)

> `#` 与脚本输出行前缀一一对应;本节全部由脚本完成,无需人工、无需信号源。3.1 脚本展开为 8 行({Emulation,Normal}×4 档)。

| # | 操作 / 命令 | 预期 | 结果 |
|---|---|---|---|
| 1.1 | `--version` | 三库版本齐全;打印被测 CLI 的 sha256 | |
| 1.2 | `-L` | 列出 `sipeed-slogic-analyzer` 驱动 | |
| 1.3 | `--protocol-decoders uart --show` | UART decoder 能加载 | |
| 2.1 | `-d ... --scan`(`-l 4`) | 识别 1 台 SLogic32U3,打印 VID:PID + S/N | |
| 2.2 | `-d ... --show` | 列出 D0..D31、采样率表、config 键 | |
| 2.3 | 链路速率(Linux sysfs / macOS ioreg 自动探测) | 运行态 10G;**Windows 探不到**→显示 `unknown` 默认按 10G,见 §4 H2 | |
| 3.1 | 各档位 × {Emulation,Normal} 实测速率(写 `/dev/null`,读驱动 `-l 4` avg) | 每行 avg ≥ 期望的 90%、100% 收齐 | |
| 3.2 | maxspeed:`pattern=USB connection test` 裸链路冲刺 | avg ≥ 标准(常大幅超标,10G≈986) | |
| 3.3 | `logic_channels=32:samplerate=1400m` | 速率被截到 200 MHz 并告警(档位联动) | |
| 3.4 | stress:20 次 open/采集/close 循环(`--stress-iters` 可调) | 全成功,无崩/无泄漏 | |
| 4.1 | 解码黄金 `.sr`(`--golden-dir`:UART,按需 SPI/I²C) | 与黄金输出一致 | |

> macOS 首次运行 CLI 产物若被 Gatekeeper 拦,内部测试放行即可(非 GUI 签名范畴)。

### 已知问题

- **Windows 吞吐掉速(2026-10)**:即便确认插在 10G 口,3.1/3.2 实测仅约 **430 MB/s**(≈ Linux 的一半;裸 USB-test 也只有 ~414,Linux 同设备 986)。瓶颈在 **WinUSB 传输层**(非设备/固件——同一设备 Linux 满速),属驱动侧问题(transfer size / 队列深度 / RAW_IO),定位与修复另立任务。Windows 回归暂以"功能链全过 + 对应链路档达标"为准,满速 10G 以 Linux 为准。

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

- [ ] 三平台 §3 脚本各跑一次均 PASS(Windows 见「已知问题」)。
- [ ] §4 人工项按触发条件完成(每次发布至少 H1)。
- [ ] 失败项已立 issue、修复、重跑。
- [ ] → 以上完成后才按 [release-process.md](release-process.md) 打 tag。

脚本结尾打印一行可直接粘贴到下表的记录(固件 / build / 操作人自填):

| 日期 | 固件 | 上位机 build | 平台 | 序列号 | 操作人 | 结论 |
|---|---|---|---|---|---|---|
| | | | | | | |
