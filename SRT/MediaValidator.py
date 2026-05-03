"""
MediaValidator — 视频/音频时长缺陷检测模块

纯 ffmpeg 依赖（不含 ffprobe），自动探测 ffmpeg 路径。

检测流程:
  1. 采集指标: CD (容器时长), ADD (解码音频时长), TVF (视频总帧数)
  2. 计算派生指标: avg_fps, gaps
  3. 决策树分类缺陷类型
  4. 返回诊断结果字典

缺陷分类（仅保留真正的问题）:
  A2  moov/mvhd duration 字段错误  → 重新 remux
  C1  视频丢帧(视频短于音频)       → 比例修正
  C2  音频提前结束(音频短于视频)   → aresample 修正
  E1  文件截断或损坏               → 重新获取

注: VFR (可变帧率) 是 OBS 录屏的正常行为，不是缺陷。
    AAC padding 帧导致解码时长短于容器也是编码器常见行为。
    两者共同导致 CD > ADD 偏差，统一归类为 C2。

共享工具函数:
  ensure_audio_duration(video_path, output_wav, sr=44100, ch=2)
    — 提取音频，自动检测并 aresample 修正时长偏差
    VocalSeparator._prepare_audio() 和 AudioSeparator.extract_audio()
    均应调用此函数替代直接 ffmpeg。
"""

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class MediaMetrics:
    """采集到的指标"""
    container_duration: float = 0.0          # CD
    decoded_audio_duration: float = 0.0      # ADD
    total_video_frames: int = 0              # TVF
    avg_frame_rate: float = 0.0              # TVF / CD (近似)
    container_audio_gap: float = 0.0         # CD - ADD
    drift_rate_pct: float = 0.0              # (CD-ADD)/ADD*100
    is_vfr: bool = False
    source_path: str = ""


@dataclass
class DiagnosisResult:
    """检测结果"""
    status: str = "ok"          # ok / defect / error
    defect_type: str = ""
    defect_name: str = ""
    severity: str = "none"
    metrics: MediaMetrics = field(default_factory=MediaMetrics)
    suggested_action: str = ""
    details: str = ""


DEFECT_INFO = {
    "A2": ("moov/mvhd duration 字段错误", "minor", "重新 remux 即可"),
    "C1": ("视频丢帧(视频短于音频)", "moderate", "下游比例修正"),
    "C2": ("音频编解码时长不匹配", "minor", "aresample 对齐时间轴"),
    "E1": ("文件截断或损坏", "severe", "重新获取源文件"),
}


# ---------------------------------------------------------------------------
# 核心检测类
# ---------------------------------------------------------------------------

class MediaValidator:
    """视频时长缺陷检测器 — 纯 ffmpeg 实现"""

    class _FfPaths:
        def __init__(self):
            self.bin = None
            self.cli = "ffmpeg"

    def __init__(self):
        self._ff = self._FfPaths()

    # ── ffmpeg 路径自动探测 ────────────────────────────────────────

    def _ensure_ffmpeg(self) -> str:
        if self._ff.bin:
            return self._ff.bin
        candidates = [
            Path(__file__).resolve().parent.parent
            / ".venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries" / "ffmpeg.exe",
            Path(__file__).resolve().parent.parent / "tools" / "ffmpeg.exe",
        ]
        for p in candidates:
            if p.is_file():
                self._ff.bin = str(p)
                return self._ff.bin
        try:
            subprocess.run(["ffmpeg", "-version"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=5)
            self._ff.bin = "ffmpeg"
            return "ffmpeg"
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        raise RuntimeError(
            "找不到 ffmpeg. 请安装并确保在 PATH 中, "
            "或放置到 Translate_video/tools/ 下."
        )

    def _run(self, args: list, timeout: int = 300) -> str:
        ff = self._ensure_ffmpeg()
        cmd = [ff] + args
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
            return out.decode("utf-8", errors="replace")
        except subprocess.CalledProcessError as e:
            logger.warning(f"ffmpeg 异常退出: {e}\n{e.output.decode('utf-8', errors='replace')[:500]}")
            raise
        except subprocess.TimeoutExpired:
            logger.warning(f"ffmpeg 超时 (>{timeout}s)")
            raise

    def _run_safe(self, args: list, timeout: int = 300) -> str:
        """有输出就算成功, 不因 exit code != 0 抛出"""
        ff = self._ensure_ffmpeg()
        cmd = [ff] + args
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.CalledProcessError as e:
            out = e.output
        except subprocess.TimeoutExpired:
            logger.warning(f"ffmpeg 超时 (>{timeout}s)")
            return ""
        return out.decode("utf-8", errors="replace")

    # ── 指标采集 ──────────────────────────────────────────────────

    def inspect(self, video_path: str) -> MediaMetrics:
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"文件不存在: {video_path}")
        m = MediaMetrics(source_path=video_path)
        m.container_duration = self._get_container_duration(video_path)
        m.total_video_frames = self._get_video_frame_count(video_path)
        m.decoded_audio_duration = self._get_decoded_audio_duration(video_path)
        if m.container_duration > 0 and m.total_video_frames > 0:
            m.avg_frame_rate = m.total_video_frames / m.container_duration
        m.container_audio_gap = m.container_duration - m.decoded_audio_duration
        if m.decoded_audio_duration > 0:
            m.drift_rate_pct = (m.container_audio_gap / m.decoded_audio_duration) * 100
        self._detect_vfr(m)
        return m

    def _get_container_duration(self, path: str) -> float:
        out = self._run_safe(["-hide_banner", "-i", path], timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", out)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
        return 0.0

    def _get_video_frame_count(self, path: str) -> int:
        out = self._run([
            "-hide_banner", "-i", path,
            "-map", "0:v:0", "-c", "copy", "-f", "null", "-",
        ], timeout=300)
        mo = re.search(r"frame=\s*(\d+)", out)
        return int(mo.group(1)) if mo else 0

    def _get_decoded_audio_duration(self, path: str) -> float:
        sr, ch, bps = 44100, 2, 2
        with tempfile.TemporaryDirectory() as tmpdir:
            wav = os.path.join(tmpdir, "_probe.wav")
            cmd = ["-hide_banner", "-y",
                   "-i", path, "-vn",
                   "-acodec", "pcm_s16le", "-ar", str(sr), "-ac", str(ch),
                   wav]
            try:
                subprocess.check_output(
                    [self._ensure_ffmpeg()] + cmd,
                    stderr=subprocess.STDOUT, timeout=600)
            except subprocess.CalledProcessError as e:
                logger.warning(f"音频解码失败: {e.output.decode('utf-8', errors='replace')[:200]}")
                return 0.0
            if not os.path.isfile(wav):
                return 0.0
            pcm = max(0, os.path.getsize(wav) - 44)
            return pcm / (sr * ch * bps)

    def _detect_vfr(self, m: MediaMetrics):
        """检测 VFR 并记录到 metrics, VFR 本身不是缺陷"""
        if m.avg_frame_rate <= 0:
            m.is_vfr = False
            return
        nominal_rates = [23.976, 24, 25, 29.97, 30, 50, 59.94, 60]
        nearest = min(nominal_rates, key=lambda r: abs(r - m.avg_frame_rate))
        m.is_vfr = abs(m.avg_frame_rate - nearest) / nearest * 100 > 0.3

    # ── 分类决策树 ────────────────────────────────────────────────

    def classify(self, m: MediaMetrics) -> DiagnosisResult:
        """
        决策树分类。

        核心原则:
        - VFR 是正常行为, 不是缺陷
        - 音频解码时长(ADD) ≠ 容器时长(CD) 时, 根源在 AAC 编解码层
        - 偏差在 0.5s 内视为正常浮点误差
        """
        result = DiagnosisResult(metrics=m)
        gap = m.container_audio_gap
        abs_gap = abs(gap)

        # 0.5s 阈值内 → OK
        if abs_gap < 0.5:
            result.status = "ok"
            result.severity = "none"
            vfr_note = " (VFR)" if m.is_vfr else ""
            result.details = f"容器与解码时长差 {abs_gap:.3f}s, 在阈值内{vfr_note}"
            return result

        # CD > ADD 显著 → C2: 音频编解码时长不匹配
        if gap > 0.5:
            result.defect_type = "C2"
            info = DEFECT_INFO["C2"]
            result.defect_name = info[0]
            result.severity = info[1]
            result.suggested_action = info[2]
            result.status = "defect"
            vfr_info = f" (VFR, avg_fps={m.avg_frame_rate:.2f})" if m.is_vfr else ""
            result.details = (
                f"音频解码 {m.decoded_audio_duration:.2f}s < 容器 {m.container_duration:.2f}s, "
                f"差 {gap:.3f}s ({m.drift_rate_pct:.3f}%){vfr_info}"
            )
            return result

        # ADD > CD 显著 → C1: 视频丢帧
        if gap < -0.5:
            result.defect_type = "C1"
            info = DEFECT_INFO["C1"]
            result.defect_name = info[0]
            result.severity = info[1]
            result.suggested_action = info[2]
            result.status = "defect"
            result.details = (
                f"音频解码 {m.decoded_audio_duration:.2f}s > 容器 {m.container_duration:.2f}s, "
                f"差 {-gap:.3f}s"
            )
            return result

        return result

    def _set_defect(self, result: DiagnosisResult, code: str, details: str) -> DiagnosisResult:
        info = DEFECT_INFO.get(code, ("未知", "unknown", ""))
        result.status = "defect"
        result.defect_type = code
        result.defect_name = info[0]
        result.severity = info[1] if info[1] != "unknown" else result.severity
        result.suggested_action = info[2]
        result.details = details
        return result

    # ── 全流程 ────────────────────────────────────────────────────

    def diagnose(self, video_path: str) -> DiagnosisResult:
        try:
            return self.classify(self.inspect(video_path))
        except FileNotFoundError as e:
            return DiagnosisResult(status="error", details=str(e))
        except Exception as e:
            logger.exception(f"诊断失败: {e}")
            return DiagnosisResult(status="error", details=f"{type(e).__name__}: {e}")

    def format_summary(self, result: DiagnosisResult) -> str:
        m = result.metrics
        lines = [
            f"文件: {os.path.basename(m.source_path)}",
            f"  状态: {result.status}",
        ]
        if result.status == "defect":
            lines.append(f"  缺陷: {result.defect_type} - {result.defect_name}")
            lines.append(f"  严重度: {result.severity}")
            lines.append(f"  建议: {result.suggested_action}")
        lines.append(f"  详情: {result.details}")
        lines.extend([
            f"  CD (容器):  {m.container_duration:.3f}s",
            f"  ADD (解码): {m.decoded_audio_duration:.3f}s",
            f"  TVF (帧数): {m.total_video_frames}",
            f"  AVG FPS:    {m.avg_frame_rate:.3f}  ({'VFR' if m.is_vfr else 'CFR'})",
            f"  偏差:       {m.container_audio_gap:+.3f}s ({m.drift_rate_pct:+.3f}%)",
        ])
        return "\n".join(lines)

    # ── 修复 (注意: 仅修复元数据问题, 音频流修复由 ensure_audio_duration 处理) ──

    def repair(self, result: DiagnosisResult, output_path: Optional[str] = None) -> Optional[str]:
        """
        修复视频元数据（如 A2 moov 错误）。

        C1/C2 类的音频内容不匹配无法在此修复 ——
        由 ensure_audio_duration() (方案 B, aresample) 处理。

        参数:
            result: DiagnosisResult (status=defect)
            output_path: 输出路径

        返回: 修复后的视频路径, 失败返回 None
        """
        if result.status != "defect":
            logger.info("视频无缺陷, 无需修复")
            return result.metrics.source_path

        m = result.metrics
        src = m.source_path
        if not os.path.isfile(src):
            logger.error(f"源文件不存在: {src}")
            return None

        # A2: 重新 remux (修复 moov 字段)
        if result.defect_type == "A2":
            if output_path is None:
                fixed_dir = os.path.join(os.path.dirname(src) or ".", "_fixed")
                os.makedirs(fixed_dir, exist_ok=True)
                name = os.path.splitext(os.path.basename(src))[0]
                output_path = os.path.join(fixed_dir, f"{name}_remuxed.mp4")

            logger.info(f"修复 A2: 重新 remux ...")
            cmd = ["-hide_banner", "-y", "-i", src,
                   "-c", "copy",
                   "-fflags", "+genpts",
                   "-avoid_negative_ts", "make_zero",
                   "-movflags", "+faststart",
                   output_path]
            try:
                self._run(cmd, timeout=600)
                logger.info(f"Remux 完成: {output_path}")
                return output_path
            except Exception as e:
                logger.error(f"Remux 失败: {e}")
                return None

        # C1/C2: 音频时长不匹配 → 不修视频, 由 ensure_audio_duration() 处理
        if result.defect_type in ("C1", "C2"):
            logger.info(
                f"缺陷 {result.defect_type}: 音频时长不匹配, "
                f"视频无需修复 (由 ensure_audio_duration aresample 修正)"
            )
            return src

        logger.warning(f"缺陷类型 {result.defect_type} 无法自动修复, 返回原始文件")
        return src


# ---------------------------------------------------------------------------
# 共享工具函数 — 通用音频时长修正 (下游提取器统一调用)
# ---------------------------------------------------------------------------


def ensure_audio_duration(video_path: str, output_wav: str,
                          sr: int = 44100, ch: int = 2) -> str:
    """
    从视频提取 WAV 音频，若解码时长与容器时长偏差 >0.5s 则自动 aresample 修正。

    这是流水线通用的音频时长修正入口。
    VocalSeparator._prepare_audio() 和 AudioSeparator.extract_audio()
    均应调用此函数替代直接 ffmpeg。

    参数:
        video_path: 输入视频路径
        output_wav: 输出 WAV 路径（会被覆盖/创建）
        sr: 采样率 (Hz), 默认 44100
        ch: 声道数, 默认 2

    返回:
        最终 WAV 文件路径 (与 output_wav 相同，修正时内部替换)
    """
    ff = _find_ffmpeg()
    bps = 2  # s16le

    # 0. 探测容器时长
    # 提取 CD：ffmpeg -i 返回 exit code 1（无输出文件），但 stderr 中有 Duration 信息
    cd = 0.0
    try:
        rp = subprocess.run(
            [ff, "-hide_banner", "-i", video_path],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace")
        # ffmpeg -i 的 Duration 信息在 stderr 中
        combined = rp.stderr + rp.stdout
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", combined)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            cd = h * 3600 + mi * 60 + s
    except Exception:
        pass

    def _wav_dur(path: str) -> float:
        if not os.path.isfile(path):
            return 0.0
        sz = os.path.getsize(path)
        return max(0, sz - 44) / (sr * ch * bps)

    # 1. 正常提取 WAV
    # 注：CD 的探测放在步骤 0 完成了，如果没有 CD 则跳过 aresample
    logger.info(f"提取音频: {os.path.basename(video_path)} -> {os.path.basename(output_wav)}")

    if cd > 0:
        # 有 CD → 带上 -t <CD> + aresample=async=1 一次到位
        # aresample=async=1 在输入样本耗尽时自动填充静音保持 PTS 同步
        # first_pts=0 让输出首帧 PTS 对齐到 0
        # -t <CD> 让 ffmpeg 以容器时长为准输出
        logger.info(f"检测到容器时长 {cd:.2f}s，使用 aresample 对齐")
        subprocess.run(
            [ff, "-y", "-i", video_path,
             "-vn",
             "-af", "aresample=async=1:first_pts=0",
             "-acodec", "pcm_s16le",
             "-ar", str(sr), "-ac", str(ch),
             "-t", str(cd),
             output_wav],
            capture_output=True, check=True)

        # 验证修复效果
        add = _wav_dur(output_wav)
        gap = abs(cd - add)
        if gap < 0.5:
            logger.info(f"aresample 修复成功: 输出时长={add:.2f}s, 偏差={gap:.3f}s")
        else:
            logger.warning(f"aresample 修复后仍有偏差: 输出={add:.2f}s, 与容器差={gap:.3f}s")
        return output_wav

    # 2. 无 CD → 裸提（无修复）
    logger.warning("无法获取容器时长，跳过音频时长检测（输出可能偏短）")
    subprocess.run(
        [ff, "-y", "-i", video_path,
         "-vn", "-acodec", "pcm_s16le",
         "-ar", str(sr), "-ac", str(ch),
         output_wav],
        capture_output=True, check=True)
    add = _wav_dur(output_wav)
    logger.info(f"裸提取完成: 输出时长={add:.2f}s")
    return output_wav


def _find_ffmpeg() -> str:
    """探测 ffmpeg 路径 (独立函数，不依赖 MediaValidator 实例)

    ffmpeg 来源优先级: imageio_ffmpeg.get_ffmpeg_exe() -> .venv 内 -> 外部 PATH
    imageio_ffmpeg.get_ffmpeg_exe() 自动处理版本号的差异，返回正确可执行文件。
    """
    # 1. imageio_ffmpeg 绑定的 ffmpeg（优先级最高，版本无关）
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ff, "-version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=5)
        return ff
    except Exception:
        pass

    # 2. .venv/site-packages/imageio_ffmpeg/binaries/ 内（处理版本号差异：用通配符）
    binary_dir = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    for f in binary_dir.glob("ffmpeg*.exe"):
        try:
            subprocess.run([str(f), "-version"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=True, timeout=5)
            return str(f)
        except Exception:
            continue

    # 3. 外部 PATH
    try:
        subprocess.run(["ffmpeg", "-version"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=5)
        return "ffmpeg"
    except Exception:
        pass

    raise RuntimeError("找不到 ffmpeg, 请安装并确保在 PATH 中")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    parser = argparse.ArgumentParser(
        description="MediaValidator - 视频时长缺陷检测")
    parser.add_argument("video", help="视频文件路径")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--repair", action="store_true", help="检测后自动修复")
    parser.add_argument("--output", help="修复后的输出路径 (需 --repair)")
    parser.add_argument("--extract", action="store_true",
                        help="提取音频并自动 aresample 修正时长")
    args = parser.parse_args()

    validator = MediaValidator()

    # 提取音频模式
    if args.extract:
        out = args.output or (os.path.splitext(args.video)[0] + ".wav")
        out = ensure_audio_duration(args.video, out)
        print(f"音频输出: {out}")
        return 0

    # 检测
    try:
        result = validator.diagnose(args.video)
    except RuntimeError as e:
        print(f"[错误] {e}")
        return 1

    # 修复
    repaired_path = None
    if args.repair and result.status == "defect":
        logger.info(f"缺陷 {result.defect_type}: {result.defect_name}")
        logger.info(f"详情: {result.details}")
        logger.info(f"建议: {result.suggested_action}")
        repaired_path = validator.repair(result, output_path=args.output)
        if repaired_path and os.path.isfile(repaired_path) and repaired_path != args.video:
            print(f"    修复完成: {repaired_path}")
        elif repaired_path == args.video:
            print(f"    无需修复视频 (由下游处理)")
        else:
            print(f"    修复失败")

    # 输出
    output = {
        "status": result.status,
        "defect_type": result.defect_type,
        "defect_name": result.defect_name,
        "severity": result.severity,
        "suggested_action": result.suggested_action,
        "details": result.details,
        "repaired": bool(repaired_path) and repaired_path != args.video,
        "repaired_path": repaired_path if (repaired_path and repaired_path != args.video) else None,
        "metrics": {
            "container_duration": result.metrics.container_duration,
            "decoded_audio_duration": result.metrics.decoded_audio_duration,
            "total_video_frames": result.metrics.total_video_frames,
            "avg_frame_rate": result.metrics.avg_frame_rate,
            "container_audio_gap": result.metrics.container_audio_gap,
            "drift_rate_pct": result.metrics.drift_rate_pct,
            "is_vfr": result.metrics.is_vfr,
        }
    }

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print("\n" + validator.format_summary(result))

    return 0


if __name__ == "__main__":
    exit(main())
