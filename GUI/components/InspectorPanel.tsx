import React, { useState } from "react";
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
  return React.createElement(Chip, { size: "small", color, label, sx: { ml: 1 } });
};

const InspectorPanel: React.FC<InspectorPanelProps> = ({
  eventId, config, inheritedFrom, overriddenFields, loading,
  onConfigChange, onResetField, onResetSlot, onPreviewTTS,
}) => {
  if (!eventId)
    return React.createElement(Typography, { color: "text.secondary" }, "Select an event to inspect config");
  if (loading)
    return React.createElement(Box, { sx: { display: "flex", justifyContent: "center", p: 4 } }, React.createElement(CircularProgress));

  const engine = config.tts?.engine || "chattts";

  const fld = (slot: string, field: string, label: string, type: string, opts?: Record<string, any>) => {
    const value = config[slot]?.[field];
    const inh = inheritedFrom[slot] || "global";
    const isOver = overriddenFields.has(slot + "." + field);
    return React.createElement(Box, { key: slot + "." + field, sx: { mb: 1.5 } },
      React.createElement(Box, { sx: { display: "flex", alignItems: "center", mb: 0.5 } },
        React.createElement(Typography, { variant: "body2" }, label),
        React.createElement(InheritanceChip, { from: isOver ? "event" : inh })),
      type === "select" ? React.createElement(Select, {
        size: "small", fullWidth: true, value: value ?? "",
        onChange: (e: any) => onConfigChange(slot, field, e.target.value) },
        (opts?.values || []).map((v: string) => React.createElement(MenuItem, { key: v, value: v }, v))) : null,
      type === "toggle" ? React.createElement(Switch, {
        size: "small", checked: !!value,
        onChange: (e: any) => onConfigChange(slot, field, e.target.checked) }) : null,
      type === "slider" ? React.createElement(Slider, {
        size: "small", value: value ?? 0, min: opts?.min ?? 0, max: opts?.max ?? 1,
        step: opts?.step ?? 0.01, valueLabelDisplay: "auto",
        onChange: (_: any, v: any) => onConfigChange(slot, field, v as number) }) : null,
      type === "number" ? React.createElement(TextField, {
        size: "small", type: "number", fullWidth: true, value: value ?? "",
        onChange: (e: any) => onConfigChange(slot, field, parseInt(e.target.value) || 0) }) : null,
      isOver ? React.createElement(Tooltip, { title: "Reset to inherit" },
        React.createElement(IconButton, { size: "small", onClick: () => onResetField(slot, field) },
          React.createElement(RestoreIcon, { fontSize: "small" }))) : null);
  };

  const zones = [
    { id: "audio", label: "Audio Preprocess" },
    { id: "asr", label: "ASR Transcription" },
    { id: "speaker", label: "Speaker" },
    { id: "translation", label: "Translation & Gate" },
    { id: "tts", label: "TTS Synthesis" },
    { id: "emotion", label: "Emotion Control" },
    { id: "review", label: "Review" }];

  return React.createElement(Box, { sx: { width: "100%", maxWidth: 400 } },
    React.createElement(Typography, { variant: "h6", sx: { mb: 1 } }, "Config - " + eventId),
    ...zones.map(zone => React.createElement(Accordion, { key: zone.id, defaultExpanded: zone.id === "tts" },
      React.createElement(AccordionSummary, { expandIcon: React.createElement(ExpandMoreIcon) },
        React.createElement(Typography, null, zone.label),
        overriddenFields.has(zone.id) ? React.createElement(Chip, { size: "small", color: "primary", label: "modified", sx: { ml: 1 } }) : null),
      React.createElement(AccordionDetails, null,

        zone.id === "audio" && React.createElement(React.Fragment, null,
          fld("audio", "skip_demucs", "Skip Demucs", "toggle"),
          fld("audio", "demucs_model", "Demucs Model", "select", { values: DEMUCS_MODELS }),
          fld("audio", "vad_threshold", "VAD Threshold", "slider", { min: 0, max: 1, step: 0.05 }),
          fld("audio", "silence_handling", "Silence Policy", "select", { values: SILENCE_POLICIES }),
          fld("audio", "loudness_compensation", "Loudness Norm", "toggle"),
          React.createElement(Button, { size: "small", color: "warning", onClick: () => onResetSlot("audio"), sx: { mt: 1 } }, "Reset All")),

        zone.id === "asr" && React.createElement(React.Fragment, null,
          fld("asr", "model", "Whisper Model", "select", { values: ASR_MODELS }),
          fld("asr", "language", "Language", "select", { values: ["auto", "en", "zh", "ja"] }),
          fld("asr", "alignment_enabled", "Word Alignment", "toggle"),
          React.createElement(Button, { size: "small", color: "warning", onClick: () => onResetSlot("asr"), sx: { mt: 1 } }, "Reset All")),

        zone.id === "speaker" && React.createElement(React.Fragment, null,
          fld("speaker", "clustering_threshold", "Cluster Threshold", "slider", { min: 0, max: 1, step: 0.05 }),
          fld("speaker", "clustering_method", "Cluster Method", "select", { values: CLUSTERING_METHODS }),
          fld("speaker", "min_speakers", "Min Speakers", "number"),
          fld("speaker", "max_speakers", "Max Speakers", "number"),
          fld("speaker", "gender", "Gender Override", "select", { values: GENDERS.concat("neutral") }),
          React.createElement(Button, { size: "small", color: "warning", onClick: () => onResetSlot("speaker"), sx: { mt: 1 } }, "Reset All")),

        zone.id === "translation" && React.createElement(React.Fragment, null,
          fld("translation", "lang", "Target Language", "select", { values: LANGS }),
          fld("translation", "backend", "LLM Backend", "select", { values: BACKENDS }),
          fld("translation", "glossary_mode", "Glossary Mode", "select", { values: GLOSSARY_MODES }),
          React.createElement(Typography, { variant: "subtitle2", sx: { mt: 1, mb: 0.5 } }, "TextGate (§4.4)"),
          fld("translation", "gate_mode", "Gate Mode", "select", { values: GATE_MODES }),
          fld("translation", "gate_threshold_accept", "Threshold Accept (A)", "slider", { min: 0, max: 1, step: 0.01 }),
          fld("translation", "gate_threshold_reject", "Threshold Reject (C)", "slider", { min: 0, max: 1, step: 0.01 }),
          React.createElement(Button, { size: "small", color: "warning", onClick: () => onResetSlot("translation"), sx: { mt: 1 } }, "Reset All")),

        zone.id === "tts" && React.createElement(React.Fragment, null,
          fld("tts", "engine", "TTS Engine", "select", { values: TTS_ENGINES }),
          fld("tts", "voice_gender", "Voice Gender", "select", { values: GENDERS }),
          fld("tts", "speed_factor", "Speed Factor", "slider", { min: 0.5, max: 2.0, step: 0.05 }),
          fld("tts", "timing_adaptive", "Timing Adaptive", "toggle"),
          fld("tts", "timing_threshold", "Timing Tolerance", "slider", { min: 0, max: 0.5, step: 0.01 }),
          React.createElement(Typography, { variant: "subtitle2", sx: { mt: 1.5, mb: 0.5 } }, "Engine Options: " + engine),
          engine === "cosyvoice" && React.createElement(React.Fragment, null,
            fld("tts", "cosy_version", "Model Version", "select", { values: ["v2", "v3"] }),
            fld("tts", "cosy_lang", "Target Language", "select", { values: COSY_LANGS }),
            fld("tts", "cosy_num_norm", "Number Normalize", "toggle"),
            fld("tts", "cosy_fp16", "FP16 Inference", "toggle")),
          engine === "chattts" && React.createElement(React.Fragment, null,
            fld("tts", "chattts_speaker_seed", "Speaker Seed", "number"),
            fld("tts", "chattts_temperature", "Temperature", "slider", { min: 0.01, max: 2.0, step: 0.05 }),
            fld("tts", "chattts_top_k", "Top-K", "slider", { min: 1, max: 100, step: 1 }),
            fld("tts", "chattts_top_p", "Top-P", "slider", { min: 0.5, max: 1.0, step: 0.01 }),
            fld("tts", "chattts_emotion_injection", "Emotion Injection", "toggle")),
          engine === "edge" && React.createElement(React.Fragment, null,
            fld("tts", "edge_voice", "Voice Name", "select", { values: EDGE_VOICES }),
            fld("tts", "edge_pitch", "Pitch", "select", { values: PITCHES }),
            fld("tts", "edge_volume", "Volume", "select", { values: VOLUMES })),
          React.createElement(Button, { size: "small", variant: "outlined", startIcon: React.createElement(PlayArrowIcon), onClick: onPreviewTTS, sx: { mt: 2 } }, "Preview TTS"),
          React.createElement(Button, { size: "small", color: "warning", onClick: () => onResetSlot("tts"), sx: { mt: 2, ml: 1 } }, "Reset All")),

        zone.id === "emotion" && React.createElement(React.Fragment, null,
          fld("emotion", "enabled", "Emotion Enabled", "toggle"),
          fld("emotion", "fusion_strategy", "Fusion Strategy", "select", { values: EMOTION_STRATEGIES }),
          fld("emotion", "audio_weight", "Audio Weight", "slider", { min: 0, max: 1, step: 0.05 }),
          fld("emotion", "text_weight", "Text Weight", "slider", { min: 0, max: 1, step: 0.05 }),
          fld("emotion", "text_model", "Text Model", "select", { values: TEXT_MODELS }),
          React.createElement(Typography, { variant: "subtitle2", sx: { mt: 1, mb: 0.5 } }, "EmotionGate (§7.3.4)"),
          fld("emotion", "gate_max_break", "Max Break (E1)", "slider", { min: 0, max: 3, step: 0.1 }),
          fld("emotion", "gate_min_confidence", "Min Confidence (E2)", "slider", { min: 0, max: 1, step: 0.05 }),
          fld("emotion", "gate_max_conflict", "Max Conflict (E3)", "slider", { min: 0, max: 3, step: 0.1 }),
          React.createElement(Button, { size: "small", color: "warning", onClick: () => onResetSlot("emotion"), sx: { mt: 1 } }, "Reset All")),

        zone.id === "review" && React.createElement(React.Fragment, null,
          fld("review", "force_accept", "Force Accept", "toggle")))))));
};

export default InspectorPanel;
