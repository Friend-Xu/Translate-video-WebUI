import { useState, useCallback } from "react";

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

export function useConfigInspector(eventId: string | null): UseConfigInspectorReturn {
  const [config, setConfig] = useState<Record<string, any>>({});
  const [inheritedFrom, setInheritedFrom] = useState<Record<string, string>>({});
  const [overriddenFields, setOverriddenFields] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  const fetchConfig = useCallback(async () => {
    if (!eventId) return;
    setLoading(true);
    try {
      const res = await fetch('/api/timeline/config/resolve?event_id=' + eventId + '&slot=tts');
      if (res.ok) {
        const data = await res.json();
        setConfig(data.resolved || {});
        setInheritedFrom({ tts: data.inherited_from || 'global' });
      }
    } catch (e) {
      console.error('Failed to fetch config:', e);
    } finally {
      setLoading(false);
    }
  }, [eventId]);

  const handleConfigChange = useCallback(async (slot: string, field: string, value: any) => {
    if (!eventId) return;
    setConfig(prev => ({ ...prev, [slot]: { ...prev[slot], [field]: value } }));
    setOverriddenFields(prev => new Set(prev).add(slot + '.' + field));
    try {
      await fetch('/api/timeline/config/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId, slot, field, value, op: 'override' }),
      });
    } catch (e) {
      console.error('Config apply failed:', e);
    }
  }, [eventId]);

  const handleResetField = useCallback(async (slot: string, field: string) => {
    if (!eventId) return;
    setConfig(prev => {
      const next = { ...prev, [slot]: { ...prev[slot] } };
      delete next[slot][field];
      return next;
    });
    setOverriddenFields(prev => { const n = new Set(prev); n.delete(slot + '.' + field); return n; });
    try {
      await fetch('/api/timeline/config/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId, slot, field, op: 'reset' }),
      });
    } catch (e) {
      console.error('Config reset failed:', e);
    }
  }, [eventId]);

  const handleResetSlot = useCallback(async (slot: string) => {
    if (!eventId) return;
    setConfig(prev => ({ ...prev, [slot]: {} }));
    setOverriddenFields(prev => { const n = new Set(prev); for (const f of n) { if (f.startsWith(slot + '.')) n.delete(f); } return n; });
    try {
      await fetch('/api/timeline/config/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId, slot, field: '', op: 'reset' }),
      });
    } catch (e) {
      console.error('Slot reset failed:', e);
    }
  }, [eventId]);

  const handlePreviewTTS = useCallback(async () => {
    console.log('TTS preview requested for', eventId);
  }, [eventId]);

  return { config, inheritedFrom, overriddenFields, loading, handleConfigChange, handleResetField, handleResetSlot, handlePreviewTTS };
}
