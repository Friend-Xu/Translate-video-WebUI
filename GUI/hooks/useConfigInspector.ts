import { useState, useCallback, useEffect, useRef } from "react";

interface UseConfigInspectorReturn {
  config: Record<string, any>;
  inheritedFrom: Record<string, string>;
  overriddenFields: Set<string>;
  loading: boolean;
  handleConfigChange: (slot: string, field: string, value: any) => void;
  handleResetField: (slot: string, field: string) => void;
  handleResetSlot: (slot: string) => void;
  handlePreviewTTS: () => void;
}

const ALL_SLOTS = ["audio", "asr", "speaker", "translation", "tts", "emotion", "review"];

export function useConfigInspector(eventId: string | null): UseConfigInspectorReturn {
  const [config, setConfig] = useState<Record<string, any>>({});
  const [inheritedFrom, setInheritedFrom] = useState<Record<string, string>>({});
  const [overriddenFields, setOverriddenFields] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const fetchConfig = useCallback(async () => {
    if (!eventId) return;
    setLoading(true);
    try {
      const allConfig: Record<string, any> = {};
      const allInherited: Record<string, string> = {};
      for (const slot of ALL_SLOTS) {
        const res = await fetch("/api/timeline/config/resolve?event_id=" + eventId + "&slot=" + slot);
        if (res.ok) {
          const data = await res.json();
          allConfig[slot] = data.resolved || {};
          allInherited[slot] = data.inherited_from || "global";
        }
      }
      setConfig(allConfig);
      setInheritedFrom(allInherited);
    } catch (e) {
      console.error("Failed to fetch config:", e);
    } finally {
      setLoading(false);
    }
  }, [eventId]);

  useEffect(() => { fetchConfig(); }, [fetchConfig]);

  const handleConfigChange = useCallback(async (slot: string, field: string, value: any) => {
    if (!eventId) return;
    setConfig(prev => ({ ...prev, [slot]: { ...prev[slot], [field]: value } }));
    setOverriddenFields(prev => new Set(prev).add(slot + "." + field));

    const send = async () => {
      try {
        await fetch("/api/timeline/config/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event_id: eventId, slot, field, value, op: "override" }),
        });
      } catch (e) {
        console.error("Config apply failed:", e);
      }
    };

    const needsDebounce = typeof value === "number";
    if (needsDebounce) {
      const key = slot + "." + field;
      if (debounceTimers.current[key]) clearTimeout(debounceTimers.current[key]);
      debounceTimers.current[key] = setTimeout(send, 300);
    } else {
      send();
    }
  }, [eventId]);

  const handleResetField = useCallback(async (slot: string, field: string) => {
    if (!eventId) return;
    setConfig(prev => { const next = { ...prev, [slot]: { ...prev[slot] } }; delete next[slot][field]; return next; });
    setOverriddenFields(prev => { const n = new Set(prev); n.delete(slot + "." + field); return n; });
    try {
      await fetch("/api/timeline/config/apply", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_id: eventId, slot, field, op: "reset" }),
      });
    } catch (e) { console.error("Config reset failed:", e); }
  }, [eventId]);

  const handleResetSlot = useCallback(async (slot: string) => {
    if (!eventId) return;
    setConfig(prev => ({ ...prev, [slot]: {} }));
    setOverriddenFields(prev => { const n = new Set(prev); for (const f of n) { if (f.startsWith(slot + ".")) n.delete(f); } return n; });
    try {
      await fetch("/api/timeline/config/apply", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_id: eventId, slot, field: "", op: "reset" }),
      });
    } catch (e) { console.error("Slot reset failed:", e); }
  }, [eventId]);

  const handlePreviewTTS = useCallback(async () => {
    console.log("TTS preview for", eventId);
  }, [eventId]);

  return { config, inheritedFrom, overriddenFields, loading, handleConfigChange, handleResetField, handleResetSlot, handlePreviewTTS };
}
