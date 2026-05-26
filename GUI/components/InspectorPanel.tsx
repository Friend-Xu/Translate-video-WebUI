import React from "react";
import { Accordion, AccordionSummary, AccordionDetails, Typography, Box, Select, MenuItem, Slider, Switch, Button, Chip, Tooltip, IconButton, CircularProgress, TextField } from "@mui/material";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import RestoreIcon from "@mui/icons-material/Restore";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";

interface InspectorPanelProps {
  eventId: string | null;
  config: Record<string, any>;
  inheritedFrom: Record<string, string>;
  overriddenFields: Set<string>;
  loading: boolean;
  onConfigChange: (slot: string, field: string, value: any) => void;
  onResetField: (slot: string, field: string) => void;
  onResetSlot: (slot: string) => void;
  onPreviewTTS: () => void;
}

const TTS_ENGINES = ["chattts", "cosyvoice", "edge"];
const ASR_MODELS = ["tiny", "base", "small", "medium", "turbo", "large-v2", "large-v3"];
const EMOTION_STRATEGIES = ["weighted_average", "max_confidence", "audio_primary", "text_primary"];
const SILENCE_POLICIES = ["keep", "trim", "expand"];
const DEMUCS_MODELS = ["htdemucs", "htdemucs_ft", "htdemucs_6s"];
const CLUSTERING_METHODS = ["agglomerative", "spectral", "umap_hdbscan"];
const GLOSSARY_MODES = ["OFF", "ALL", "RELEVANCE", "CONTEXTUAL"];
const GATE_MODES = ["logic_gate", "joint_formula"];
const GENDERS = ["auto", "male", "female"];
const TEXT_MODELS = ["distiluse", "bert-base", "roberta-emotion"];
const BACKENDS = ["deepseek", "openai", "local_dict", "custom_api"];
const LANGS = ["zh", "en", "ja", "ko"];
const COSY_LANGS = ["zh", "en", "ja", "ko", "yue"];
const EDGE_VOICES = ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "en-US-JennyNeural", "ja-JP-NanamiNeural"];
const PITCHES = ["+0Hz", "-5Hz", "+5Hz", "+10Hz"];
const VOLUMES = ["+0%", "+10%", "+20%", "-10%"];

const InheritanceChip: React.FC<{ from: string }> = ({ from }) => {
  const color = from === "event" ? "primary" as const : from === "speaker" ? "secondary" as const : "default" as const;
  const label = from === "event" ? "Override" : from === "speaker" ? "Speaker" : "Global";
  return <Chip size="small" color={color} label={label} sx={{ ml: 1 }} />;
};

const InspectorPanel: React.FC<InspectorPanelProps> = ({
  eventId, config, inheritedFrom, overriddenFields, loading,
  onConfigChange, onResetField, onResetSlot, onPreviewTTS,
}) => {
  if (!eventId)
    return <Typography color="text.secondary">Select an event to inspect config</Typography>;
  if (loading)
    return <Box sx={{ display: "flex", justifyContent: "center", p: 4 }}><CircularProgress /></Box>;

  const engine = config.tts?.engine || "chattts";

  const renderField = (slot: string, field: string, label: string, type: string, opts?: Record<string, any>) => {
    const value = config[slot]?.[field];
    const inh = inheritedFrom[slot] || "global";
    const isOver = overriddenFields.has(slot + "." + field);
    return (
      <Box key={slot + "." + field} sx={{ mb: 1.5 }}>
        <Box sx={{ display: "flex", alignItems: "center", mb: 0.5 }}>
          <Typography variant="body2">{label}</Typography>
          <InheritanceChip from={isOver ? "event" : inh} />
        </Box>
        {type === "select" && (
          <Select size="small" fullWidth value={value ?? ""}
            onChange={(e: any) => onConfigChange(slot, field, e.target.value)}>
            {(opts?.values || []).map((v: string) => <MenuItem key={v} value={v}>{v}</MenuItem>)}
          </Select>
        )}
        {type === "toggle" && (
          <Switch size="small" checked={!!value}
            onChange={(e: any) => onConfigChange(slot, field, e.target.checked)} />
        )}
        {type === "slider" && (
          <Slider size="small" value={value ?? 0} min={opts?.min ?? 0} max={opts?.max ?? 1}
            step={opts?.step ?? 0.01} valueLabelDisplay="auto"
            onChange={(_: any, v: any) => onConfigChange(slot, field, v as number)} />
        )}
        {type === "number" && (
          <TextField size="small" type="number" fullWidth value={value ?? ""}
            onChange={(e: any) => onConfigChange(slot, field, parseInt(e.target.value) || 0)} />
        )}
        {isOver && (
          <Tooltip title="Reset to inherit">
            <IconButton size="small" onClick={() => onResetField(slot, field)}>
              <RestoreIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Box>
    );
  };

  const zones = [
    { id: "audio", label: "Audio Preprocess" },
    { id: "asr", label: "ASR Transcription" },
    { id: "speaker", label: "Speaker" },
    { id: "translation", label: "Translation & Gate" },
    { id: "tts", label: "TTS Synthesis" },
    { id: "emotion", label: "Emotion Control" },
    { id: "review", label: "Review" },
  ];

  return (
    <Box sx={{ width: "100%", maxWidth: 400 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>Config - {eventId}</Typography>
      {zones.map(zone => (
        <Accordion key={zone.id} defaultExpanded={zone.id === "tts"}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography>{zone.label}</Typography>
            {overriddenFields.has(zone.id) && (
              <Chip size="small" color="primary" label="modified" sx={{ ml: 1 }} />
            )}
          </AccordionSummary>
          <AccordionDetails>
            {zone.id === "audio" && (
              <>
                {renderField("audio", "skip_demucs", "Skip Demucs", "toggle")}
                {renderField("audio", "demucs_model", "Demucs Model", "select", { values: DEMUCS_MODELS })}
                {renderField("audio", "vad_threshold", "VAD Threshold", "slider", { min: 0, max: 1, step: 0.05 })}
                {renderField("audio", "silence_handling", "Silence Policy", "select", { values: SILENCE_POLICIES })}
                {renderField("audio", "loudness_compensation", "Loudness Norm", "toggle")}
                <Button size="small" color="warning" onClick={() => onResetSlot("audio")} sx={{ mt: 1 }}>Reset All</Button>
              </>
            )}
            {zone.id === "asr" && (
              <>
                {renderField("asr", "model", "Whisper Model", "select", { values: ASR_MODELS })}
                {renderField("asr", "language", "Language", "select", { values: ["auto", "en", "zh", "ja"] })}
                {renderField("asr", "alignment_enabled", "Word Alignment", "toggle")}
                <Button size="small" color="warning" onClick={() => onResetSlot("asr")} sx={{ mt: 1 }}>Reset All</Button>
              </>
            )}
            {zone.id === "speaker" && (
              <>
                {renderField("speaker", "clustering_threshold", "Cluster Threshold", "slider", { min: 0, max: 1, step: 0.05 })}
                {renderField("speaker", "clustering_method", "Cluster Method", "select", { values: CLUSTERING_METHODS })}
                {renderField("speaker", "min_speakers", "Min Speakers", "number")}
                {renderField("speaker", "max_speakers", "Max Speakers", "number")}
                {renderField("speaker", "gender", "Gender Override", "select", { values: GENDERS.concat("neutral") })}
                <Button size="small" color="warning" onClick={() => onResetSlot("speaker")} sx={{ mt: 1 }}>Reset All</Button>
              </>
            )}
            {zone.id === "translation" && (
              <>
                {renderField("translation", "lang", "Target Language", "select", { values: LANGS })}
                {renderField("translation", "backend", "LLM Backend", "select", { values: BACKENDS })}
                {renderField("translation", "glossary_mode", "Glossary Mode", "select", { values: GLOSSARY_MODES })}
                <Typography variant="subtitle2" sx={{ mt: 1, mb: 0.5 }}>TextGate (§4.4)</Typography>
                {renderField("translation", "gate_mode", "Gate Mode", "select", { values: GATE_MODES })}
                {renderField("translation", "gate_threshold_accept", "Threshold Accept (A)", "slider", { min: 0, max: 1, step: 0.01 })}
                {renderField("translation", "gate_threshold_reject", "Threshold Reject (C)", "slider", { min: 0, max: 1, step: 0.01 })}
                <Button size="small" color="warning" onClick={() => onResetSlot("translation")} sx={{ mt: 1 }}>Reset All</Button>
              </>
            )}
            {zone.id === "tts" && (
              <>
                {renderField("tts", "engine", "TTS Engine", "select", { values: TTS_ENGINES })}
                {renderField("tts", "voice_gender", "Voice Gender", "select", { values: GENDERS })}
                {renderField("tts", "speed_factor", "Speed Factor", "slider", { min: 0.5, max: 2.0, step: 0.05 })}
                {renderField("tts", "timing_adaptive", "Timing Adaptive", "toggle")}
                {renderField("tts", "timing_threshold", "Timing Tolerance", "slider", { min: 0, max: 0.5, step: 0.01 })}
                <Typography variant="subtitle2" sx={{ mt: 1.5, mb: 0.5 }}>Engine Options: {engine}</Typography>
                {engine === "cosyvoice" && (
                  <>
                    {renderField("tts", "cosy_version", "Model Version", "select", { values: ["v2", "v3"] })}
                    {renderField("tts", "cosy_lang", "Target Language", "select", { values: COSY_LANGS })}
                    {renderField("tts", "cosy_num_norm", "Number Normalize", "toggle")}
                    {renderField("tts", "cosy_fp16", "FP16 Inference", "toggle")}
                  </>
                )}
                {engine === "chattts" && (
                  <>
                    {renderField("tts", "chattts_speaker_seed", "Speaker Seed", "number")}
                    {renderField("tts", "chattts_temperature", "Temperature", "slider", { min: 0.01, max: 2.0, step: 0.05 })}
                    {renderField("tts", "chattts_top_k", "Top-K", "slider", { min: 1, max: 100, step: 1 })}
                    {renderField("tts", "chattts_top_p", "Top-P", "slider", { min: 0.5, max: 1.0, step: 0.01 })}
                    {renderField("tts", "chattts_emotion_injection", "Emotion Injection", "toggle")}
                  </>
                )}
                {engine === "edge" && (
                  <>
                    {renderField("tts", "edge_voice", "Voice Name", "select", { values: EDGE_VOICES })}
                    {renderField("tts", "edge_pitch", "Pitch", "select", { values: PITCHES })}
                    {renderField("tts", "edge_volume", "Volume", "select", { values: VOLUMES })}
                  </>
                )}
                <Button size="small" variant="outlined" startIcon={<PlayArrowIcon />} onClick={onPreviewTTS} sx={{ mt: 2 }}>Preview TTS</Button>
                <Button size="small" color="warning" onClick={() => onResetSlot("tts")} sx={{ mt: 2, ml: 1 }}>Reset All</Button>
              </>
            )}
            {zone.id === "emotion" && (
              <>
                {renderField("emotion", "enabled", "Emotion Enabled", "toggle")}
                {renderField("emotion", "fusion_strategy", "Fusion Strategy", "select", { values: EMOTION_STRATEGIES })}
                {renderField("emotion", "audio_weight", "Audio Weight", "slider", { min: 0, max: 1, step: 0.05 })}
                {renderField("emotion", "text_weight", "Text Weight", "slider", { min: 0, max: 1, step: 0.05 })}
                {renderField("emotion", "text_model", "Text Model", "select", { values: TEXT_MODELS })}
                <Typography variant="subtitle2" sx={{ mt: 1, mb: 0.5 }}>EmotionGate (§7.3.4)</Typography>
                {renderField("emotion", "gate_max_break", "Max Break (E1)", "slider", { min: 0, max: 3, step: 0.1 })}
                {renderField("emotion", "gate_min_confidence", "Min Confidence (E2)", "slider", { min: 0, max: 1, step: 0.05 })}
                {renderField("emotion", "gate_max_conflict", "Max Conflict (E3)", "slider", { min: 0, max: 3, step: 0.1 })}
                <Button size="small" color="warning" onClick={() => onResetSlot("emotion")} sx={{ mt: 1 }}>Reset All</Button>
              </>
            )}
            {zone.id === "review" && (
              <>
                {renderField("review", "force_accept", "Force Accept", "toggle")}
              </>
            )}
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  );
};

export default InspectorPanel;
