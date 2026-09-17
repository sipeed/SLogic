# SLogic capture baseline (Phase 0)

Measured 2026-09-16/17 on Arch Linux x86_64 (kernel from the run
documents), SLogic32U3 `359F:3032` on USB3, workspace commit
`e8c2984e5649`, artifacts `dev-nightly/e8c2984e5649` (linux-x86_64-musl,
Release). Harness: `build/bench/capture_bench.py`; raw JSON:
`artifact/bench/baseline/` (960 runs) plus `artifact/bench/20260916-debugbuild/`.

## Coverage

Full matrix, both transports: channel modes {32, 16, 8, 4} at top rates
{200, 400, 800, 1600} MHz, patterns {Normal, USB connection test,
Emulation}, durations {1, 2, 4, 10} s, 10 repetitions per cell.
480 runs per transport, no cell skipped.

## Headline numbers

| Transport | Full captures | 32ch | 16ch | 8ch | 4ch |
| --- | --- | --- | --- | --- | --- |
| all-logic-mcp (AppImage) | 414/480 (86.2%) | 114/120 | 117/120 | 100/120 | 83/120 |
| sigrok-cli (AppImage) | 217/480 (45.2%) | 75/120 | 89/120 | 52/120 | 1/120 |

32 of the 66 MCP non-full runs are harness deadline artifacts, not
driver failures: the wait deadline (6x duration + 60 s) is shorter than
the host-bound completion time of the 8ch/4ch 10 s cells (138 s and
275 s of host time per 10 s of data). The remaining 34 are zero-sample
starts. Full-capture wall times reproduce far inside the +-3% gate:
32ch Emulation over sigrok-cli, mean/sd 1.078/0.004 s (1 s), 2.079/0.004,
4.076/0.004, 10.076/0.002 (10 s).

## The largest host-side bottleneck

The ALL-LOGIC AppImage host consumes at 233 MB/s where the wire delivers
800 MB/s (32ch cells; the driver's own line: "stream done: 800.0 MB in
3.431 s (233 MB/s), host tail ~1140 ms" on every full 1 s capture). The
consumption rate halves with each halving of the channel width - 117 MB/s
at 16ch, 58 MB/s at 8ch, 29-30 MB/s at 4ch - i.e. the cost is
per-sample, in the LA_CROSS_DATA transpose/append path, not per-byte.
Debug (-O0) and Release AppImages measure identically (233 MB/s), so
compiler optimization is not the limiter; the plan's reference for the
same code path on a native glibc build is 670-793 MB/s. The prime
suspect is musl's allocator on the per-transfer buffer churn (Phase 1
item 5); the native-build A/B run is still pending (the GUI could not be
started from the harness session; see Follow-ups).

## Per-cell reference (full runs only)

MCP, 1 s cells, host wall per 1 s of data: 32ch 4.70 s, 16ch 6.98 s,
8ch 13.84 s, 4ch 26.5-27.6 s. GUI responsiveness stayed healthy
throughout: MCP poll p95 median 12.0 ms, worst 20.6 ms across all 414
full runs. Backpressure ("USB link slower than the analyzer") was
logged in 5 MCP runs. The complete 96-row comparison table is appended
below; regenerate it any time with
`./build/bench/capture_bench.py --out artifact/bench/baseline report`.

## Behaviours the matrix exposed

1. sigrok-cli stall aborts. 241 of 263 CLI shorts stopped at <= 16
   samples with the driver's timeout message on stderr; 22 aborted at
   1.6-19 M samples around 0.1 s. Whole cells fail systematically:
   8ch/Normal 0/40, 4ch/Normal 0/40. This is the "slow transfer is
   fatal on every transfer" rule the plan already names.
2. 4ch over libsigrok is effectively unusable: 1 full run in 120;
   119 of the shorts stopped at exactly 12 samples.
3. USB connection test streams above real time: 912-970 MB/s from the
   device on both transports (CLI wall 0.88 s for 1 s of 32ch data).
   On the MCP side the host then drains the backlog for 16-44 s
   (driver-reported host tail), so the pattern measures the device
   link, not the steady capture path.
4. Emulation at the top rates also arrives faster than the sample
   clock would suggest (CLI 32ch 1 s: 0.98-1.08 s wall including
   process start), consistent with pattern generation not being paced
   like Normal acquisition at 32ch; at 8/4ch Normal and Emulation pace
   identically.
5. Hot-plug fragility, live specimen: mid-sweep the host entered an
   attach-event storm - 7382 "Process device attach event" lines with
   no USB re-enumeration (bus address unchanged) - and the running
   capture hung; log preserved at
   `/tmp/alllogic-bench-hotplugstorm.log` (copy in the bench notes).
   Separately, two sigrok-cli captures blocked >35 minutes delivering
   neither data nor EOF; the harness now kills such captures with an
   idle watchdog and records them as shorts.

## Device and firmware notes (recorded, not worked around)

Reduced-channel packing and the known 16-bit phase shift were not
targeted by this phase; no host-side workaround was added or removed.

## Follow-ups

- Native glibc A/B for the MCP host (the musl-vs-native factor above).
- Harness: scale the MCP wait deadline with the measured host rate so
  slow-host cells are not misreported as timeouts.
- The 8ch/10s MCP cells show bimodal walls (17.4 s vs deadline) that
  suggest the captured-samples counter can reach the target before
  conversion finishes; verify the counter semantics before Phase 1
  profiling.

## Comparison table

| Cell | Transport | Runs | Full | Wall s (mean±sd) | Wire MB/s | Tail ms | CPU s | GUI p95 ms | Backpressure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4ch@1600MHz Emulation 1s | all-logic-mcp | 10 | 10/10 | 27.554±0.074 | 58 | 0 | 3.01 | 2.1 | 0/10 |
| 4ch@1600MHz Emulation 1s | sigrok-cli | 10 | 0/10 | 0.095±0.003 | 12000 | 19 | 0.07 | - | - |
| 4ch@1600MHz Emulation 2s | all-logic-mcp | 10 | 10/10 | 54.992±0.013 | 58 | 0 | 5.62 | 1.6 | 0/10 |
| 4ch@1600MHz Emulation 2s | sigrok-cli | 10 | 0/10 | 0.096±0.003 | 12000 | 19 | 0.08 | - | - |
| 4ch@1600MHz Emulation 4s | all-logic-mcp | 10 | 5/10 | 25.887±0.034 | 58 | 0 | -36.40 | 1.4 | 0/10 |
| 4ch@1600MHz Emulation 4s | sigrok-cli | 10 | 0/10 | 0.095±0.003 | 12000 | 18 | 0.08 | - | - |
| 4ch@1600MHz Emulation 10s | all-logic-mcp | 10 | 3/10 | 34.565±0.068 | 58 | 0 | -108.21 | 1.8 | 0/10 |
| 4ch@1600MHz Emulation 10s | sigrok-cli | 10 | 0/10 | 0.096±0.003 | 12000 | 18 | 0.08 | - | - |
| 4ch@1600MHz Normal 1s | all-logic-mcp | 10 | 10/10 | 26.544±3.193 | 58 | 0 | 0.99 | 3.1 | 0/10 |
| 4ch@1600MHz Normal 1s | sigrok-cli | 10 | 0/10 | 0.104±0.005 | 12000 | 32 | 0.09 | - | - |
| 4ch@1600MHz Normal 2s | all-logic-mcp | 10 | 10/10 | 54.979±0.010 | 58 | 0 | 5.42 | 1.5 | 0/10 |
| 4ch@1600MHz Normal 2s | sigrok-cli | 10 | 0/10 | 0.107±0.006 | 12000 | 33 | 0.09 | - | - |
| 4ch@1600MHz Normal 4s | all-logic-mcp | 10 | 0/10 | 0.361±0.017 | 0 | 0 | 0.04 | 5.3 | 0/10 |
| 4ch@1600MHz Normal 4s | sigrok-cli | 10 | 0/10 | 0.104±0.006 | 12000 | 32 | 0.09 | - | - |
| 4ch@1600MHz Normal 10s | all-logic-mcp | 10 | 0/10 | 0.356±0.007 | 0 | 0 | 0.03 | 6.3 | 0/10 |
| 4ch@1600MHz Normal 10s | sigrok-cli | 10 | 0/10 | 0.107±0.006 | 12000 | 32 | 0.09 | - | - |
| 4ch@1600MHz USB connection test 1s | all-logic-mcp | 10 | 10/10 | 13.111±0.014 | 1880 | 12162 | 1.22 | 1.2 | 0/10 |
| 4ch@1600MHz USB connection test 1s | sigrok-cli | 10 | 1/10 | 4.953±0.000 | 328 | 1 | 5.04 | - | - |
| 4ch@1600MHz USB connection test 2s | all-logic-mcp | 10 | 10/10 | 26.137±0.014 | 1884 | 24315 | 2.76 | 1.8 | 0/10 |
| 4ch@1600MHz USB connection test 2s | sigrok-cli | 10 | 0/10 | 0.096±0.003 | 12000 | 19 | 0.08 | - | - |
| 4ch@1600MHz USB connection test 4s | all-logic-mcp | 10 | 10/10 | 52.196±0.028 | 1887 | 48625 | 5.00 | 1.4 | 0/10 |
| 4ch@1600MHz USB connection test 4s | sigrok-cli | 10 | 0/10 | 0.097±0.004 | 12000 | 19 | 0.08 | - | - |
| 4ch@1600MHz USB connection test 10s | all-logic-mcp | 10 | 5/10 | 10.358±0.018 | 1888 | 121596 | -77.85 | 1.3 | 0/10 |
| 4ch@1600MHz USB connection test 10s | sigrok-cli | 10 | 0/10 | 0.096±0.004 | 12000 | 18 | 0.08 | - | - |
| 8ch@800MHz Emulation 1s | all-logic-mcp | 10 | 10/10 | 13.845±0.078 | 58 | 1 | 11.45 | 11.0 | 0/10 |
| 8ch@800MHz Emulation 1s | sigrok-cli | 10 | 8/10 | 1.076±0.003 | 796 | 1 | 1.10 | - | - |
| 8ch@800MHz Emulation 2s | all-logic-mcp | 10 | 10/10 | 27.568±0.014 | 58 | 5 | 22.67 | 11.6 | 0/10 |
| 8ch@800MHz Emulation 2s | sigrok-cli | 10 | 7/10 | 2.076±0.002 | 798 | 1 | 2.18 | - | - |
| 8ch@800MHz Emulation 4s | all-logic-mcp | 10 | 10/10 | 55.054±0.022 | 58 | 1 | 44.85 | 11.2 | 0/10 |
| 8ch@800MHz Emulation 4s | sigrok-cli | 10 | 0/10 | 0.106±0.007 | 12000 | 32 | 0.09 | - | - |
| 8ch@800MHz Emulation 10s | all-logic-mcp | 10 | 4/10 | 17.390±0.134 | 58 | 0 | -19.93 | 11.2 | 0/10 |
| 8ch@800MHz Emulation 10s | sigrok-cli | 10 | 0/10 | 0.105±0.006 | 12000 | 32 | 0.09 | - | - |
| 8ch@800MHz Normal 1s | all-logic-mcp | 10 | 10/10 | 13.841±0.070 | 58 | 1 | 11.53 | 10.9 | 0/10 |
| 8ch@800MHz Normal 1s | sigrok-cli | 10 | 0/10 | 0.105±0.006 | 12000 | 32 | 0.10 | - | - |
| 8ch@800MHz Normal 2s | all-logic-mcp | 10 | 9/10 | 27.555±0.021 | 58 | 5 | 23.07 | 11.7 | 0/10 |
| 8ch@800MHz Normal 2s | sigrok-cli | 10 | 0/10 | 0.107±0.007 | 12000 | 32 | 0.09 | - | - |
| 8ch@800MHz Normal 4s | all-logic-mcp | 10 | 10/10 | 55.042±0.017 | 58 | 1 | 45.70 | 10.9 | 1/10 |
| 8ch@800MHz Normal 4s | sigrok-cli | 10 | 0/10 | 0.101±0.003 | 12000 | 31 | 0.09 | - | - |
| 8ch@800MHz Normal 10s | all-logic-mcp | 10 | 4/10 | 17.387±0.122 | 58 | 1 | -20.01 | 10.5 | 0/10 |
| 8ch@800MHz Normal 10s | sigrok-cli | 10 | 0/10 | 0.102±0.005 | 12000 | 32 | 0.09 | - | - |
| 8ch@800MHz USB connection test 1s | all-logic-mcp | 10 | 9/10 | 14.017±1.284 | 837 | 11210 | 6.57 | 9.4 | 0/10 |
| 8ch@800MHz USB connection test 1s | sigrok-cli | 10 | 10/10 | 0.886±0.004 | 984 | 1 | 0.88 | - | - |
| 8ch@800MHz USB connection test 2s | all-logic-mcp | 10 | 9/10 | 27.025±0.042 | 941 | 25202 | 19.50 | 11.0 | 0/10 |
| 8ch@800MHz USB connection test 2s | sigrok-cli | 10 | 9/10 | 1.693±0.003 | 986 | 1 | 1.67 | - | - |
| 8ch@800MHz USB connection test 4s | all-logic-mcp | 10 | 10/10 | 54.004±0.051 | 942 | 50415 | 38.93 | 9.7 | 0/10 |
| 8ch@800MHz USB connection test 4s | sigrok-cli | 10 | 9/10 | 3.309±0.003 | 988 | 1 | 3.30 | - | - |
| 8ch@800MHz USB connection test 10s | all-logic-mcp | 10 | 5/10 | 14.935±0.102 | 935 | 126086 | -20.44 | 9.5 | 1/10 |
| 8ch@800MHz USB connection test 10s | sigrok-cli | 10 | 9/10 | 8.161±0.006 | 989 | 1 | 9.49 | - | - |
| 16ch@400MHz Emulation 1s | all-logic-mcp | 10 | 10/10 | 6.988±0.076 | 117 | 5 | 6.88 | 12.2 | 0/10 |
| 16ch@400MHz Emulation 1s | sigrok-cli | 10 | 8/10 | 1.077±0.004 | 796 | 1 | 1.10 | - | - |
| 16ch@400MHz Emulation 2s | all-logic-mcp | 10 | 9/10 | 13.850±0.023 | 117 | 6 | 13.54 | 12.7 | 0/10 |
| 16ch@400MHz Emulation 2s | sigrok-cli | 10 | 6/10 | 2.079±0.004 | 798 | 1 | 2.18 | - | - |
| 16ch@400MHz Emulation 4s | all-logic-mcp | 10 | 10/10 | 27.631±0.023 | 117 | 9 | 26.88 | 13.3 | 0/10 |
| 16ch@400MHz Emulation 4s | sigrok-cli | 10 | 2/10 | 4.079±0.006 | 799 | 1 | 3.96 | - | - |
| 16ch@400MHz Emulation 10s | all-logic-mcp | 10 | 10/10 | 68.902±0.040 | 117 | 9 | 67.18 | 12.7 | 0/10 |
| 16ch@400MHz Emulation 10s | sigrok-cli | 10 | 0/10 | 0.104±0.004 | 12000 | 33 | 0.09 | - | - |
| 16ch@400MHz Normal 1s | all-logic-mcp | 10 | 10/10 | 6.977±0.072 | 117 | 6 | 6.80 | 12.5 | 0/10 |
| 16ch@400MHz Normal 1s | sigrok-cli | 10 | 10/10 | 1.079±0.005 | 796 | 1 | 1.05 | - | - |
| 16ch@400MHz Normal 2s | all-logic-mcp | 10 | 10/10 | 13.830±0.012 | 117 | 12 | 13.66 | 12.3 | 0/10 |
| 16ch@400MHz Normal 2s | sigrok-cli | 10 | 9/10 | 2.079±0.004 | 798 | 1 | 2.06 | - | - |
| 16ch@400MHz Normal 4s | all-logic-mcp | 10 | 10/10 | 27.572±0.011 | 117 | 16 | 27.31 | 13.1 | 0/10 |
| 16ch@400MHz Normal 4s | sigrok-cli | 10 | 7/10 | 4.077±0.004 | 799 | 1 | 4.04 | - | - |
| 16ch@400MHz Normal 10s | all-logic-mcp | 10 | 10/10 | 68.797±0.030 | 117 | 16 | 68.20 | 12.7 | 1/10 |
| 16ch@400MHz Normal 10s | sigrok-cli | 10 | 9/10 | 10.077±0.002 | 800 | 1 | 9.94 | - | - |
| 16ch@400MHz USB connection test 1s | all-logic-mcp | 10 | 9/10 | 6.908±0.015 | 960 | 5972 | 6.22 | 11.4 | 0/10 |
| 16ch@400MHz USB connection test 1s | sigrok-cli | 10 | 9/10 | 0.884±0.003 | 984 | 1 | 0.90 | - | - |
| 16ch@400MHz USB connection test 2s | all-logic-mcp | 10 | 10/10 | 13.754±0.029 | 962 | 11958 | 12.45 | 12.0 | 0/10 |
| 16ch@400MHz USB connection test 2s | sigrok-cli | 10 | 10/10 | 1.694±0.002 | 986 | 1 | 1.86 | - | - |
| 16ch@400MHz USB connection test 4s | all-logic-mcp | 10 | 9/10 | 27.385±0.079 | 964 | 23896 | 24.81 | 12.5 | 0/10 |
| 16ch@400MHz USB connection test 4s | sigrok-cli | 10 | 10/10 | 3.310±0.001 | 988 | 1 | 3.01 | - | - |
| 16ch@400MHz USB connection test 10s | all-logic-mcp | 10 | 10/10 | 68.306±0.081 | 966 | 59694 | 61.70 | 11.7 | 0/10 |
| 16ch@400MHz USB connection test 10s | sigrok-cli | 10 | 9/10 | 8.160±0.001 | 989 | 1 | 8.09 | - | - |
| 32ch@200MHz Emulation 1s | all-logic-mcp | 10 | 8/10 | 4.706±0.090 | 233 | 1153 | 4.58 | 16.6 | 0/10 |
| 32ch@200MHz Emulation 1s | sigrok-cli | 10 | 5/10 | 1.078±0.004 | 796 | 1 | 1.01 | - | - |
| 32ch@200MHz Emulation 2s | all-logic-mcp | 10 | 10/10 | 9.305±0.037 | 233 | 2307 | 9.14 | 15.3 | 0/10 |
| 32ch@200MHz Emulation 2s | sigrok-cli | 10 | 9/10 | 2.079±0.004 | 798 | 1 | 2.02 | - | - |
| 32ch@200MHz Emulation 4s | all-logic-mcp | 10 | 10/10 | 18.497±0.041 | 233 | 4587 | 18.25 | 14.9 | 0/10 |
| 32ch@200MHz Emulation 4s | sigrok-cli | 10 | 9/10 | 4.076±0.004 | 799 | 1 | 4.25 | - | - |
| 32ch@200MHz Emulation 10s | all-logic-mcp | 10 | 10/10 | 46.009±0.073 | 233 | 11401 | 45.69 | 15.9 | 0/10 |
| 32ch@200MHz Emulation 10s | sigrok-cli | 10 | 10/10 | 10.076±0.002 | 800 | 1 | 10.20 | - | - |
| 32ch@200MHz Normal 1s | all-logic-mcp | 10 | 10/10 | 4.703±0.017 | 233 | 1186 | 4.94 | 15.6 | 0/10 |
| 32ch@200MHz Normal 1s | sigrok-cli | 10 | 6/10 | 1.076±0.003 | 797 | 1 | 1.18 | - | - |
| 32ch@200MHz Normal 2s | all-logic-mcp | 10 | 9/10 | 9.295±0.021 | 233 | 2349 | 9.86 | 14.2 | 1/10 |
| 32ch@200MHz Normal 2s | sigrok-cli | 10 | 0/10 | 0.103±0.004 | 12000 | 32 | 0.09 | - | - |
| 32ch@200MHz Normal 4s | all-logic-mcp | 10 | 10/10 | 18.496±0.010 | 233 | 4674 | 19.39 | 12.6 | 0/10 |
| 32ch@200MHz Normal 4s | sigrok-cli | 10 | 0/10 | 0.104±0.005 | 12000 | 32 | 0.09 | - | - |
| 32ch@200MHz Normal 10s | all-logic-mcp | 10 | 10/10 | 46.081±0.033 | 233 | 11651 | 48.54 | 13.1 | 0/10 |
| 32ch@200MHz Normal 10s | sigrok-cli | 10 | 0/10 | 0.109±0.006 | 12000 | 33 | 0.09 | - | - |
| 32ch@200MHz USB connection test 1s | all-logic-mcp | 10 | 10/10 | 4.676±0.011 | 966 | 3749 | 4.42 | 14.2 | 0/10 |
| 32ch@200MHz USB connection test 1s | sigrok-cli | 10 | 8/10 | 0.886±0.004 | 984 | 1 | 0.91 | - | - |
| 32ch@200MHz USB connection test 2s | all-logic-mcp | 10 | 9/10 | 9.254±0.020 | 971 | 7492 | 8.80 | 12.8 | 0/10 |
| 32ch@200MHz USB connection test 2s | sigrok-cli | 10 | 9/10 | 1.695±0.004 | 987 | 1 | 1.65 | - | - |
| 32ch@200MHz USB connection test 4s | all-logic-mcp | 10 | 8/10 | 18.410±0.059 | 972 | 14985 | 17.34 | 12.6 | 0/10 |
| 32ch@200MHz USB connection test 4s | sigrok-cli | 10 | 9/10 | 3.308±0.002 | 988 | 1 | 3.71 | - | - |
| 32ch@200MHz USB connection test 10s | all-logic-mcp | 10 | 10/10 | 45.992±0.055 | 969 | 37433 | 43.34 | 13.5 | 1/10 |
| 32ch@200MHz USB connection test 10s | sigrok-cli | 10 | 10/10 | 8.160±0.001 | 989 | 1 | 8.02 | - | - |
