import { useState, useEffect } from "react";
import {
  Box, Typography, Select, MenuItem, TextField, Slider,
  FormControlLabel, Switch, Button, Alert,
} from "@mui/material";
import type { PipelineConfig } from "../../types";

interface Props {
  config: PipelineConfig;
  onConfigChange: <K extends keyof PipelineConfig>(key: K, value: PipelineConfig[K]) => void;
}

export default function CosyVoiceTTSPanel({ config, onConfigChange }: Props) {
  const [modelExists, setModelExists] = useState<boolean | null>(null);
  const [previewAudio, setPreviewAudio] = useState<string>("");
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    fetch("/api/models")
      .then((r) => r.json())
      .then((data: { models?: Array<{ id: string; exists: boolean }> }) => {
        const cv = (data.models || []).find((m) => m.id === "cosyvoice");
        setModelExists(cv ? cv.exists : null);
      })
      .catch(() => setModelExists(null));
  }, []);

  const handleExtractVocals = async () => {
    if (!config.videoPath) return;
    try {
      const resp = await fetch(
        `/api/files/find?path=${encodeURIComponent(config.videoPath)}`
      );
      if (!resp.ok) return;
      const info = await resp.json();
      const dir = info.dir || "";
      const name = (info.name || "").replace(/\.[^.]+$/, "");
      const vocalsPath = `${dir}/${name}_project/01_extract/vocals.wav`;
      onConfigChange("cosyvoiceTtsPromptAudio", vocalsPath);
    } catch {
      // 静默失败
    }
  };

  const handlePreview = async () => {
    if (!config.cosyvoiceTtsPromptAudio) return;
    setPreviewing(true);
    try {
      const resp = await fetch("/api/tts/preview-cosyvoice", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_version: config.cosyvoiceTtsModelVersion,
          model_path: config.cosyvoiceTtsModelPath || undefined,
          prompt_audio: config.cosyvoiceTtsPromptAudio,
          prompt_text: config.cosyvoiceTtsPromptText,
          fp16: config.cosyvoiceTtsFp16,
          speed: config.cosyvoiceTtsSpeed,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setPreviewAudio(data.audio_base64 || "");
      }
    } catch {
      // 静默失败
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <Box sx={{ mt: 1.5, p: 1.5, border: "1px solid", borderColor: "divider", borderRadius: 1 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        CosyVoice TTS 配置
      </Typography>

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">模型版本</Typography>
        <Select
          size="small" fullWidth
          value={config.cosyvoiceTtsModelVersion}
          onChange={(e) => onConfigChange("cosyvoiceTtsModelVersion", e.target.value)}
          sx={{ mt: 0.5 }}
        >
          <MenuItem value="v3">CosyVoice 3.0 (推荐)</MenuItem>
          <MenuItem value="v2">CosyVoice 2.0</MenuItem>
        </Select>
      </Box>

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">模型路径</Typography>
        <TextField
          size="small" fullWidth
          value={config.cosyvoiceTtsModelPath}
          onChange={(e) => onConfigChange("cosyvoiceTtsModelPath", e.target.value)}
          placeholder="./models/CosyVoice2-0.5B"
          sx={{ mt: 0.5 }}
        />
        {modelExists === false && (
          <Alert severity="warning" sx={{ mt: 0.5 }}>
            未检测到 CosyVoice 模型，请下载模型到 models/ 目录
          </Alert>
        )}
      </Box>

      <FormControlLabel
        control={
          <Switch
            size="small"
            checked={config.cosyvoiceTtsFp16}
            onChange={(e) => onConfigChange("cosyvoiceTtsFp16", e.target.checked)}
          />
        }
        label={<Typography variant="caption">FP16 推理（降低显存占用）</Typography>}
      />

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">
          参考说话人音频 (zero-shot prompt, ≤30s)
        </Typography>
        <Box sx={{ display: "flex", gap: 0.5, mt: 0.5 }}>
          <TextField
            size="small" fullWidth
            value={config.cosyvoiceTtsPromptAudio}
            onChange={(e) => onConfigChange("cosyvoiceTtsPromptAudio", e.target.value)}
            placeholder="留空从 Demucs 人声自动提取"
          />
          <Button
            size="small" variant="outlined"
            onClick={handleExtractVocals}
            disabled={!config.videoPath}
            sx={{ whiteSpace: "nowrap", minWidth: "auto" }}
          >
            自动
          </Button>
        </Box>
      </Box>

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">
          参考音频转录文本（与参考音频内容一致）
        </Typography>
        <TextField
          size="small" fullWidth multiline minRows={2}
          value={config.cosyvoiceTtsPromptText}
          onChange={(e) => onConfigChange("cosyvoiceTtsPromptText", e.target.value)}
          placeholder="输入参考音频中说话人的文字内容..."
          sx={{ mt: 0.5 }}
        />
      </Box>

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">
          语速: {config.cosyvoiceTtsSpeed.toFixed(1)}x
        </Typography>
        <Slider
          size="small"
          min={0.5} max={2.0} step={0.1}
          value={config.cosyvoiceTtsSpeed}
          onChange={(_, v) => onConfigChange("cosyvoiceTtsSpeed", v as number)}
          marks={[
            { value: 0.5, label: "0.5x" },
            { value: 1.0, label: "1.0x" },
            { value: 1.5, label: "1.5x" },
            { value: 2.0, label: "2.0x" },
          ]}
          sx={{ mt: 0.5 }}
        />
      </Box>

      <Box sx={{ mb: 1, display: "flex", gap: 1, alignItems: "center" }}>
        <Button
          size="small" variant="outlined"
          onClick={handlePreview}
          disabled={previewing || !config.cosyvoiceTtsPromptAudio}
        >
          {previewing ? "合成中..." : "试听"}
        </Button>
        {previewAudio && (
          <audio
            controls
            src={`data:audio/wav;base64,${previewAudio}`}
            style={{ height: 32, maxWidth: 220 }}
          />
        )}
      </Box>

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">
          Worker 数: 1（串行安全模式，与 ChatTTS 相同）
        </Typography>
      </Box>
    </Box>
  );
}
