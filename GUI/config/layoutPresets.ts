/**
 * layoutPresets.ts — 模式驱动布局路由
 *
 * 每个 Mode 下各区域渲染的组件映射。
 * AppShell 消费此配置，动态加载对应组件。
 */
import { LAYOUT_PRESETS } from '../types/modes'
import type { Mode } from '../types/modes'

export { LAYOUT_PRESETS, MODE_META, ALL_MODES, ALL_INSPECTOR_TABS } from '../types/modes'
export type { Mode, LayoutPreset, InspectorTab, ModeMeta } from '../types/modes'

/** 根据模式获取 Rail 组件名（用于动态加载） */
export function getRailComponent(mode: Mode): string | null {
  return LAYOUT_PRESETS[mode]?.railComponent ?? null
}

/** 根据模式获取默认激活的 Dock 视图 */
export function getDefaultDockView(mode: Mode): 'log' | 'aiTrace' | 'patchDiff' | 'taskOutput' | 'debug' {
  return LAYOUT_PRESETS[mode]?.defaultDockView ?? 'log'
}
