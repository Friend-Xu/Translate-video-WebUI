# Media Duration Defect Classification

## 目标
自动化检测视频中音频/视频时长不一致的缺陷，分类后采取对应修复策略。

---

## 一、检测指标

每个视频需要采集 5 个原始指标：

| # | 指标 | 来源 | 单位 |
|---|------|------|------|
| 1 | Container Duration (CD) | `moov/mvhd` box | s |
| 2 | Video Stream Duration (VSD) | `stts` 表最后一帧 PTS | s |
| 3 | Audio Stream Duration (ASD_pkt) | `stts` 表最后一个音频包 PTS | s |
| 4 | Decoded Audio Duration (ADD) | 实际解码 PCM 样本数 / 采样率 | s |
| 5 | Total Video Frames (TVF) | 视频帧计数 | frames |

推导指标：
- Audio Decode Ratio (ADR) = ADD / ASD_pkt (解码/包时长比, 正常 ≈ 1.0)
- Video Frame Rate (VFR) = TVF / VSD
- Audio Container Gap = CD - ADD
- Audio Stream Gap = ASD_pkt - ADD
- Duration Drift Rate = (CD - ADD) / ADD × 100%

---

## 二、缺陷分类图谱

### Type A: 容器元数据错误 (Container Metadata Error)

**A1 — VFR 容器时长虚高** ← 本次遇到的
- 特征: CD ≈ ASD_pkt ≈ VSD > ADD，且差值 ≈ (TVF / 30 - TVF / avg_fps)
- 常见于: OBS 录屏、NVIDIA ShadowPlay、游戏录制
- 修复: VFR → CFR 转码 (`-vsync cfr -r 30 -c:a copy`) 
- 偏移类型: 线性比例漂移

**A2 — moov/mvhd duration 字段错误**
- 特征: CD ≠ VSD ≈ ASD_pkt ≈ ADD
- 常见于: 快速二次封装工具、流式写入中断
- 修复: 重新 remux (`-c copy -fflags +genpts`)
- 偏移类型: 纯尾部偏移

**A3 — Audio stts 表错误**
- 特征: ASD_pkt ≠ ADD，但 VSD ≈ CD
- 常见于: 部分硬件编码器、老版本 x264+AAC
- 修复: 重新解码无压缩重编码
- 偏移类型: 可能非线性

---

### Type B: 编码器层问题 (Codec-Level Issues)

**B1 — AAC encoder delay / priming samples**
- 特征: ADD 比 ASD_pkt 短 21~1024 采样 (48000Hz 下约 0.4~21ms)
- 差异极小，通常可忽略
- 修复: `-af aresample=async=1:first_pts=0` 或直接忽略

**B2 — AAC 末尾填充帧 (Terminal Pad)**
- 特征: ASD_pkt > ADD，差值 = N × 1024 采样 (N 个 AAC 帧)
- 常见于: 部分编码器会写多余填零帧到末尾
- 修复: `apad=whole_dur=<container_dur>` (静音补回)
- 偏移类型: 纯尾部偏移

**B3 — Gapless playback metadata**
- 特征: ASD_pkt 含 iTunSMPB / `elst` 编辑偏移，ADD 与之匹配
- 常见于: iTunes 转码的 M4A、Apple 生态文件
- 修复: `-use_editlist 0` 忽略编辑列表

---

### Type C: 录制管线问题 (Recording Pipeline Issues)

**C1 — 视频丢帧 (Dropped Video Frames)**
- 特征: VSD > ADD，视频持续时间比音频长
- 常见于: 低性能设备录制、高负载录屏
- 修复: CFR 转码或下游比例修正

**C2 — 音频流提前结束 (Audio Trail Truncated)**
- 特征: ADD < VSD，且音频末尾无 pad 帧
- 常见于: 硬件编码器 crash、异常中断、部分手机录像
- 修复: 下游比例修正，或补静音后标注"末尾无声"

**C3 — 音频起止不同步 (Audio Start Offset)**
- 特征: ASD_pkt 的 start_time ≠ 0 (视频 start_time = 0)
- 常见于: 流媒体录制、多源合流、时间戳错位
- 修复: `-af aresample=async=1:first_pts=0`，或在时间戳上做平移

---

### Type D: 后期编辑残留 (Post-Processing Artifacts)

**D1 — 无损剪辑残留 (Lossless Cut)**
- 特征: 剪辑点之后容器 duration 未更新
- 常见于: LosslessCut、SolveigMM Video Splitter
- 修复: 重新 remux (`-c copy -fflags +genpts`)
- 识别: 剪辑点处有非 0 的 edit list offset

**D2 — 拼接残留 (Concat Artifact)**
- 特征: 拼接处音频时间戳有跳变
- 常见于: 在线视频下载后拼接、会议录制拼接
- 修复: 两遍 — 先修复每段，再按拼接点映射

---

### Type E: 文件损坏 (File Corruption)

**E1 — 截断文件 (Truncated)**
- 特征: moov box duration ≠ 实际可解码长度，末尾有大量 error concealment
- 常见于: 下载未完成、传输中断
- 修复: 用截断部分尽力处理，标记残缺

**E2 — 音频 Bitstream 损坏**
- 特征: 解码时出现大量 AAC error concealment，ADD 异常
- 常见于: 网络流媒体录制的丢包产物
- 修复: 重新获取源文件

---

## 三、自动化检测流程

```
输入视频
  │
  ▼
步骤 1: 采集 5 个指标 (CD, VSD, ASD_pkt, ADD, TVF)
  │
  ▼
步骤 2: 计算派生指标 (ADR, VFR, Gaps, DriftRate)
  │
  ▼
步骤 3: 缺陷分类决策树

  if ADD > CD (音频比容器长):
    → C3 (音频起止不同步) / B3 (gapless)

  elif abs(CD - ADD) < 0.5s:
    → 正常 / B1 (encoder delay 可忽略)

  elif abs(CD - ADD) < 2.0s:
    → 检查 ASD_pkt
      if ASD_pkt ≈ CD:
        → A2 (moov 错误)
      elif ASD_pkt > ADD 且差值倍数于 1024:
        → B2 (terminal pad)
      else:
        → A3 / D1 (需进一步判断)

  elif CD - ADD > 2.0s (大偏差):
    → 检查 ASD_pkt
      if ASD_pkt ≈ ADD (包时间戳 ≈ 解码时长):
        → 检查 VFR
          if avg_fps < nominal_fps:
            → A1 (VFR 时长虚高)
          else:
            → C2 (音频提前结束)
      elif ASD_pkt ≈ CD (包时间戳 ≈ 容器):
        → A1 (VFR, 需要帧率确认)
      elif ASD_pkt > ADD 且差值倍数于 1024:
        → B2 (大量 pad 帧)
      else:
        → E1 (截断) / E2 (损坏)

  │
  ▼
步骤 4: 采取修复策略

  缺陷类型         首要修复                    备选修复
  A1 (VFR)    VFR → CFR 转码             下游比例修正
  A2 (moov)   只用 ffmpeg remux            -
  B2 (pad)    apad 补回或忽略              -
  C2 (截断)    下游比例修正                补静音
  C3 (偏移)    aresample sync             时间轴平移
  D1 (剪辑)    重新 remux                  -
  E1/E2        标记失败，通知人工         -

  │
  ▼
步骤 5: 标记结果

  输出: {
    "status": "ok" | "fixed" | "failed",
    "defect_type": "A1" | "B2" | ...,
    "原始指标": {...},
    "修复操作": "vfr_to_cfr" | "remux" | "proportional_correction" | ...,
    "修正因子": 1.00552 (如有),
    "偏差": 13.48 (秒),
  }
```

## 四、实现位置建议

检测函数建议放在 `SRT/VocalSeparator.py` 的 `_prepare_audio()` 中，或者独立成一个 `MediaValidator` 类。

方案一：集成到 VocalSeparator（简单）
```
VocalSeparator.__init__()
  └─ _detect_defect()    ← 新增：自动检测并分类
  └─ _prepare_audio()    ← 已有：提取音频 + 按缺陷类型修复
```

方案二：独立检测模块（推荐，更通用）
```
SRT/MediaValidator.py
  ├─ inspect(path)        → 采集 5 个指标
  ├─ classify(metrics)    → 返回缺陷类型
  └─ repair(path, type)   → 返回修复后的视频/音频路径
```

---

## 五、需要验证的点

1. ASD_pkt (最后一包的 PTS) vs ADD (解码样本数) 的关系
   - 当前只有粗略数据，需要用 `ffmpeg -show_packets` 精确确认
2. add 修复后的视频用 whisperX 跑一遍验证时间戳是否对齐
3. 除了 LongTest1，找其他类型的问题视频做测试集
