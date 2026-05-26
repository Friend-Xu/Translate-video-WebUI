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
    return React.createElement(Box, { sx: { display: "flex", justifyContent: "center", p: 4 } },
      React.createElement(CircularProgress));

  const renderField = (slot: string, field: string, label: string, type: string, opts?: Record<string, any>) => {
    const value = config[slot]?.[field];
    const inh = inheritedFrom[slot] || "global";
    const isOverridden = overriddenFields.has(slot + "." + field);
    return React.createElement(Box, { key: slot + "." + field, sx: { mb: 1.5 } },
      React.createElement(Box, { sx: { display: "flex", alignItems: "center", mb: 0.5 } },
        React.createElement(Typography, { variant: "body2" }, label),
        React.createElement(InheritanceChip, { from: isOverridden ? "event" : inh })),
      type === "select" ? React.createElement(Select, {
        size: "small", fullWidth: true, value: value ?? "",
        onChange: (e: any) => onConfigChange(slot, field, e.target.value) },
        (opts?.values || []).map((v: string) =>
          React.createElement(MenuItem, { key: v, value: v }, v))) : null,
      type === "toggle" ? React.createElement(Switch, {
        size: "small", checked: !!value,
        onChange: (e: any) => onConfigChange(slot, field, e.target.checked) }) : null,
      type === "slider" ? React.createElement(Slider, {
        size: "small", value: value ?? 0, min: opts?.min ?? 0, max: opts?.max ?? 1,
        step: opts?.step ?? 0.01, valueLabelDisplay: "auto",
        onChange: (_: any, v: any) => onConfigChange(slot, field, v as number) }) : null,
      isOverridden ? React.createElement(Tooltip, { title: "Reset to inherit" },
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
        zone.id === "tts" && React.createElement(React.Fragment, null,
          renderField("tts", "engine", "Engine", "select", { values: TTS_ENGINES }),
          renderField("tts", "speed_factor", "Speed", "slider", { min: 0.5, max: 2.0, step: 0.05 }),
          renderField("tts", "timing_adaptive", "Timing Adapt", "toggle"),
          React.createElement(Button, { size: "small", variant: "outlined", startIcon: React.createElement(PlayArrowIcon), onClick: onPreviewTTS, sx: { mt: 1 } }, "Preview"),
          React.createElement(Button, { size: "small", color: "warning", onClick: () => onResetSlot("tts"), sx: { mt: 1, ml: 1 } }, "Reset All")),
        zone.id === "asr" && React.createElement(React.Fragment, null,
          renderField("asr", "model", "Model", "select", { values: ASR_MODELS }),
          renderField("asr", "language", "Language", "select", { values: ["auto","en","zh","ja"] }),
          renderField("asr", "alignment_enabled", "Alignment", "toggle")),
        zone.id === "audio" && React.createElement(React.Fragment, null,
          renderField("audio", "skip_demucs", "Skip Demucs", "toggle"),
          renderField("audio", "vad_threshold", "VAD Threshold", "slider", { min: 0, max: 1, step: 0.05 }),
          renderField("audio", "loudness_compensation", "Loudness Norm", "toggle")),
        zone.id === "translation" && React.createElement(React.Fragment, null,
          renderField("translation", "lang", "Target Lang", "select", { values: ["zh","en","ja","ko"] }),
          renderField("translation", "backend", "Backend", "select", { values: ["deepseek","openai","local_dict"] })),
        zone.id === "emotion" && React.createElement(React.Fragment, null,
          renderField("emotion", "enabled", "Enabled", "toggle"),
          renderField("emotion", "fusion_strategy", "Strategy", "select", { values: EMOTION_STRATEGIES }),
          renderField("emotion", "audio_weight", "Audio Weight", "slider", { min: 0, max: 1, step: 0.05 }),
          renderField("emotion", "text_weight", "Text Weight", "slider", { min: 0, max: 1, step: 0.05 })),
        zone.id === "speaker" && React.createElement(React.Fragment, null,
          renderField("speaker", "clustering_threshold", "Cluster Thr.", "slider", { min: 0, max: 1, step: 0.05 }),
          renderField("speaker", "gender", "Gender", "select", { values: ["auto","male","female","neutral"] })),
        zone.id === "review" && React.createElement(React.Fragment, null,
          renderField("review", "force_accept", "Force Accept", "toggle")))))));
};

export default InspectorPanel;
