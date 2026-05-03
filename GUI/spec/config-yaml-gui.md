# Spec: Config.yaml GUI 集成

## Objective
将 `SRT/Config.yaml`（字幕分段预设参数）暴露到 GUI 高级设置中，用户可在界面调整参数，持久化保存，重启后自动恢复，出错可回退到出厂默认值。

## Tech Stack
- 存储：`GUI/settings.json`（用户偏好持久化）
- 备份：`SRT/Config.yaml.bak`（出厂默认值只读备份）
- 运行时：`SRT/Config.yaml`（pipeline 子进程读取）
- 无新增外部依赖

## Project Structure
```
GUI/
├── server.py              # 新增 settings 读写 + Config.yaml 备份/恢复/写回
├── settings.json          # 新增：用户偏好持久化（gitignore）
├── spec/
│   └── config-yaml-gui.md # 本文件
SRT/
├── Config.yaml            # 运行时文件，GUI 写入用户自定义值
├── Config.yaml.bak        # 首次自动创建，出厂默认值（gitignore）
```

## 三层存储职责

| 文件 | 职责 | 谁写 | 谁读 |
|------|------|------|------|
| `Config.yaml.bak` | 出厂默认值，只读 | 首次修改前自动复制 | 「恢复默认」时读 |
| `Config.yaml` | 运行时文件，pipeline 子进程读 | GUI 在启动 pipeline 前合并写入 | `Json_Convert_Srt.py` |
| `GUI/settings.json` | GUI 用户偏好持久化 | 用户修改时写 | GUI 启动时读 |

## settings.json Schema

只存用户主动修改过的字段，未修改的不存（运行时从 Config.yaml 读原值）。

```json
{
  "subtitle": {
    "ja": { "max_chars": 40, "merge_chars": 80 },
    "en": { "max_chars": 25 },
    "zh": {},
    "ko": {},
    "default": {}
  }
}
```

- 语言 key 与 Config.yaml 一致：`ja` / `en` / `zh` / `ko` / `default`
- 只包含用户修改过的参数，空对象表示该语言未做任何自定义
- 预留顶层 key（如 `tts`、`translate`）供后续扩展

## GUI 界面设计（高级设置新增卡片）

在「高级设置」页面新增「字幕分段参数」卡片，位于现有内容之后。

### 布局

```
┌─ 字幕分段参数 ─────────────────────────────────────────┐
│                                                         │
│  当前语言预设: 日语 (ja)   [恢复默认值]                 │
│                                                         │
│  ── 基础参数 ──                                         │
│  单段最大字符数     [35]     max_chars                  │
│  最少显示时长(秒)   [0.8]    min_duration               │
│  最大允许间隙(秒)   [0.3]    max_gap                    │
│                                                         │
│  ── 合并参数 ──                                         │
│  合并触发间隔(秒)   [0.3]    merge_gap                  │
│  合并后最大字符数   [70]     merge_chars                │
│  合并后最大时长(秒) [5.0]    merge_dur_max              │
│                                                         │
│  ── 拆分参数 ──                                         │
│  拆分触发字符数     [160]    split_chars                │
│  拆分触发时长(秒)   [8.0]    split_dur                  │
│  拆分后最少字符数   [5]      split_chars_min            │
│                                                         │
│  标点符号（只读展示，不暴露编辑）                       │
│  句末标点: 。！？!?…」』                                │
│  停顿标点: 、，；,;:                                    │
└─────────────────────────────────────────────────────────┘
```

### 控件规则

| 控件 | 说明 |
|------|------|
| 语言预设标签 | 读取 `config.lang`，自动显示对应语言（`ja→日语`、`en→英语`、`zh→中文`、`ko→韩语`、其他→默认） |
| 数值输入框 | `TextField type="number"`，`inputProps={{ step, min, max }}` 根据参数类型设置步进和范围 |
| 恢复默认值按钮 | 从 `.bak` 恢复该语言的全部参数，清除 `settings.json` 里该语言的自定义 |
| 标点符号 | 只读 `Typography` 展示，不提供编辑（极少需要改，改了容易出错） |
| `space_optimization` | 不暴露（自动由语言决定：英语=true，其他=false） |
| `formatter` | 不暴露（自动由语言决定：`japanese`/`english`/`chinese`/`korean`/`general`） |

### 参数范围约束

| 参数 | min | max | step | 类型 |
|------|-----|-----|------|------|
| max_chars | 10 | 100 | 1 | int |
| min_duration | 0.3 | 3.0 | 0.1 | float |
| max_gap | 0.1 | 3.0 | 0.1 | float |
| merge_gap | 0.1 | 2.0 | 0.1 | float |
| merge_chars | 20 | 200 | 5 | int |
| merge_dur_max | 2.0 | 15.0 | 0.5 | float |
| split_chars | 50 | 500 | 10 | int |
| split_dur | 3.0 | 20.0 | 0.5 | float |
| split_chars_min | 1 | 20 | 1 | int |

## API 设计

### GET /api/settings
读取 `GUI/settings.json`，返回用户自定义值。文件不存在返回 `{}`。

### POST /api/settings
写入 `GUI/settings.json`。请求 body 结构与 settings.json 一致。

### POST /api/settings/reset
`{ "language": "ja" }` — 恢复指定语言的默认值（从 `.bak` 读取），清除 settings.json 里该语言条目。

## 后端流程

### 启动 pipeline 前写回 Config.yaml

```python
def apply_subtitle_settings():
    """合并 settings.json 的自定义值到 Config.yaml"""
    settings = load_settings()           # 读 GUI/settings.json
    presets = load_config_yaml()          # 读 SRT/Config.yaml（当前值）
    for lang, overrides in settings.get("subtitle", {}).items():
        if lang in presets and overrides:
            presets[lang].update(overrides)
    write_config_yaml(presets)            # 写回 SRT/Config.yaml
```

在 `start_pipeline()` 调用 `_run_job()` 之前调用 `apply_subtitle_settings()`。

### 备份逻辑

```python
def ensure_backup():
    """首次修改前创建 .bak，只创建一次"""
    bak = CONFIG_PATH.with_suffix('.yaml.bak')
    if not bak.exists():
        shutil.copy2(CONFIG_PATH, bak)
```

在 `apply_subtitle_settings()` 开头调用。

### 恢复逻辑

```python
def reset_language(language: str):
    """恢复指定语言的默认值"""
    bak = CONFIG_PATH.with_suffix('.yaml.bak')
    defaults = yaml.safe_load(bak.read_text('utf-8'))
    presets = load_config_yaml()
    if language in defaults:
        presets[language] = defaults[language]
    write_config_yaml(presets)
    # 清除 settings.json 里的该语言条目
    settings = load_settings()
    settings.get("subtitle", {}).pop(language, None)
    save_settings(settings)
```

## 前端流程

### useConfig 扩展

`useConfig.ts` 新增：
- `subtitleSettings` 状态（从 `/api/settings` 加载）
- `updateSubtitleParam(lang, key, value)` — 更新并 POST 到 `/api/settings`
- `resetSubtitleLang(lang)` — 调 `/api/settings/reset`

### AdvancedSettings 组件

在现有内容后新增「字幕分段参数」卡片：
- 启动时从 `/api/settings` 读取自定义值
- 无自定义值时显示 Config.yaml 的默认值（通过 `/api/system/info` 扩展返回或新增 GET `/api/subtitle/presets`）
- 修改后实时保存到 `/api/settings`

## 合并写入时机

在 `server.py` 的 `start_pipeline()` 中，构建 CLI args 之前调用：

```python
@app.post("/api/pipeline/run")
async def start_pipeline(req: RunRequest):
    # 1. 确保 .bak 存在
    ensure_backup()
    # 2. 合并 settings.json 到 Config.yaml
    apply_subtitle_settings()
    # 3. 原有逻辑：构建 args、启动子进程
    ...
```

## Boundaries
- **Always**: 启动 pipeline 前合并写入 Config.yaml；`.bak` 只创建不覆盖；settings.json 只存用户修改过的字段
- **Ask first**: 标点符号编辑能力；`space_optimization`/`formatter` 暴露；并发 pipeline 写 Config.yaml 的锁机制
- **Never**: 不修改 `Json_Convert_Srt.py` 的加载逻辑；不删除 `.bak`；不在 pipeline 运行中修改 Config.yaml

## Success Criteria
1. GUI 高级设置显示当前语言对应的字幕分段参数，值来自 Config.yaml
2. 用户修改参数后，settings.json 立即持久化，重启 GUI 后参数自动恢复
3. 启动 pipeline 时，Config.yaml 被合并写入用户自定义值
4. 点击「恢复默认值」后，该语言参数恢复到 .bak 的出厂值
5. 出错时（YAML 格式异常等），自动从 .bak 恢复 Config.yaml
6. `SRT/Config.yaml.bak` 和 `GUI/settings.json` 加入 .gitignore

## Open Questions
- 无
