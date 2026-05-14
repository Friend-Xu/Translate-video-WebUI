import { useState, useEffect, useRef } from "react";
import {
  Box, Typography, Card, IconButton, Collapse, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, Chip, Button,
  LinearProgress, CircularProgress, Alert, Stack, Tooltip,
} from "@mui/material";
import {
  Refresh, ExpandMore, ExpandLess, Download, CheckCircle,
  Cloud, ErrorOutline, Stop,
} from "@mui/icons-material";

interface EnvData {
  gpu_name: string;
  vram_total_gb: number;
  vram_free_gb: number;
  cpu_cores: number;
  ram_total_gb: number;
  ram_available_gb: number;
  cuda_version: string;
  pytorch_version: string;
  python_version: string;
  os_name: string;
  has_gpu: boolean;
}

interface ModelData {
  id: string;
  name: string;
  function: string;
  category: string;
  exists: boolean;
  partial: boolean;
  path: string;
  rel_path: string;
  size_gb: number;
  size_mb: number;
  vram_gb: number;
  downloadable: boolean;
  fit_level: string;
  fit_label: string;
  fit_color: string;
}

const CATEGORY_LABELS: Record<string, { icon: string; title: string }> = {
  subtitle: { icon: "📹", title: "字幕提取模块" },
  translate: { icon: "🌐", title: "翻译模块" },
  tts: { icon: "🔊", title: "TTS + 声音克隆模块" },
};

const FIT_CHIP_COLOR: Record<string, "success" | "info" | "warning" | "error" | "default"> = {
  recommended: "success",
  runnable: "info",
  tight: "warning",
  unusable: "error",
  cloud: "default",
};

type DownloadState = Record<string, {
  downloading: boolean;
  progress: number;
  downloaded_gb: number;
  total_gb: number;
  error: string;
}>;

export default function ModelManagerPanel() {
  const [models, setModels] = useState<ModelData[]>([]);
  const [env, setEnv] = useState<EnvData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    subtitle: true,
    translate: false,
    tts: false,
  });
  const [dl, setDl] = useState<DownloadState>({});
  const esMap = useRef<Record<string, EventSource>>({});

  const stopDownload = async (modelId: string) => {
    // 关闭 EventSource
    const es = esMap.current[modelId];
    if (es) {
      es.close();
      delete esMap.current[modelId];
    }
    // 发送取消请求
    try {
      await fetch(`/api/models/download/${modelId}/cancel`, { method: "POST" });
    } catch { /* ignore */ }
    setDl((prev) => {
      const n = { ...prev };
      delete n[modelId];
      return n;
    });
  };

  const fetchData = async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await fetch("/api/models");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setModels(data.models || []);
      setEnv(data.env || null);
    } catch (e: any) {
      setError(e?.message || "获取模型列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  const toggleCategory = (cat: string) => {
    setExpanded((prev) => ({ ...prev, [cat]: !prev[cat] }));
  };

  const startDownload = (modelId: string) => {
    // 先取消已有下载
    stopDownload(modelId);
    setDl((prev) => ({
      ...prev,
      [modelId]: { downloading: true, progress: 0, downloaded_gb: 0, total_gb: 0, error: "" },
    }));
    const es = new EventSource(`/api/models/download/${modelId}`);
    esMap.current[modelId] = es;
    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.status === "cancelled") {
          setDl((prev) => { const n = { ...prev }; delete n[modelId]; return n; });
          delete esMap.current[modelId];
          es.close();
        } else if (msg.status === "downloading") {
          setDl((prev) => ({
            ...prev,
            [modelId]: {
              downloading: true,
              progress: msg.progress,
              downloaded_gb: msg.downloaded_gb || 0,
              total_gb: msg.total_gb || 0,
              error: "",
            },
          }));
        } else if (msg.status === "completed") {
          setDl((prev) => { const n = { ...prev }; delete n[modelId]; return n; });
          delete esMap.current[modelId];
          es.close();
          fetchData();
        } else if (msg.status === "error") {
          setDl((prev) => ({
            ...prev,
            [modelId]: {
              downloading: false, progress: 0,
              downloaded_gb: 0, total_gb: 0,
              error: msg.message || "下载失败",
            },
          }));
          delete esMap.current[modelId];
          es.close();
        }
      } catch { /* ignore */ }
    };
    es.onerror = () => {
      setDl((prev) => {
        const cur = prev[modelId];
        if (cur?.downloading) {
          return {
            ...prev,
            [modelId]: { ...cur, downloading: false, error: "连接中断，请重试" },
          };
        }
        return prev;
      });
      delete esMap.current[modelId];
      es.close();
    };
  };

  const grouped: Record<string, ModelData[]> = {};
  for (const m of models) {
    (grouped[m.category] ??= []).push(m);
  }

  const fitChip = (m: ModelData) => {
    if (m.fit_level === "cloud") {
      return <Chip size="small" icon={<Cloud />} label="云端" color="default" variant="outlined" />;
    }
    const color = FIT_CHIP_COLOR[m.fit_level] || "default";
    return <Chip size="small" label={m.fit_label} color={color} />;
  };

  const statusChip = (m: ModelData) => {
    if (m.exists) {
      return (
        <Chip size="small" icon={<CheckCircle />} label="已安装" color="success" variant="outlined" />
      );
    }
    if (m.partial) {
      return (
        <Tooltip title="目录存在但关键模型文件缺失，请重新下载">
          <Chip size="small" icon={<ErrorOutline />} label="残缺" color="warning" />
        </Tooltip>
      );
    }
    const dlState = dl[m.id];
    if (dlState?.error) {
      return (
        <Tooltip title={dlState.error}>
          <Chip size="small" icon={<ErrorOutline />} label="失败" color="error" />
        </Tooltip>
      );
    }
    return <Chip size="small" label="未安装" color="default" variant="outlined" />;
  };

  const actionCell = (m: ModelData) => {
    if (m.exists && !m.partial) return <Typography variant="caption" color="text.secondary">—</Typography>;
    const dlState = dl[m.id];
    if (dlState?.downloading) {
      return (
        <Box sx={{ minWidth: 130 }}>
          <Stack spacing={0.5}>
            <Box display="flex" alignItems="center" gap={0.5}>
              <CircularProgress size={12} />
              <Typography variant="caption">{dlState.progress}%</Typography>
              <IconButton size="small" color="error" onClick={() => stopDownload(m.id)} sx={{ ml: 0.5 }}>
                <Stop fontSize="small" />
              </IconButton>
            </Box>
            <LinearProgress variant="determinate" value={dlState.progress} sx={{ height: 4, borderRadius: 2 }} />
            <Typography variant="caption" color="text.secondary">
              {dlState.downloaded_gb.toFixed(1)}/{dlState.total_gb.toFixed(1)} GB
            </Typography>
          </Stack>
        </Box>
      );
    }
    if (dlState?.error) {
      return (
        <Button size="small" variant="outlined" color="error" onClick={() => startDownload(m.id)}>
          重试
        </Button>
      );
    }
    if (!m.downloadable) return <Typography variant="caption" color="text.secondary">手动安装</Typography>;
    return (
      <Button
        size="small" variant="contained" color="primary"
        startIcon={<Download />}
        onClick={() => startDownload(m.id)}
      >
        下载
      </Button>
    );
  };

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        模型管理
      </Typography>

      {loading && (
        <Box display="flex" alignItems="center" gap={1} sx={{ mb: 1 }}>
          <CircularProgress size={16} />
          <Typography variant="caption" color="text.secondary">检测环境 & 加载模型列表...</Typography>
        </Box>
      )}

      {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}

      {/* 环境信息栏 */}
      {env && (
        <Card variant="outlined" sx={{ mb: 1.5, p: 1.5 }}>
          <Box display="flex" justifyContent="space-between" alignItems="center">
            <Typography variant="caption" fontWeight={600}>🖥 运行环境</Typography>
            <IconButton size="small" onClick={fetchData} disabled={loading}>
              <Refresh fontSize="small" />
            </IconButton>
          </Box>
          <Box sx={{ mt: 0.5, display: "flex", flexWrap: "wrap", gap: 1.5 }}>
            <Typography variant="caption" color="text.secondary">
              GPU: <b>{env.gpu_name || "无"}</b>
            </Typography>
            {env.has_gpu && (
              <>
                <Typography variant="caption" color="text.secondary">
                  VRAM: <b>{env.vram_total_gb} GB</b>
                  {env.vram_free_gb > 0 && <> (可用 ~{env.vram_free_gb.toFixed(1)} GB)</>}
                </Typography>
              </>
            )}
            <Typography variant="caption" color="text.secondary">
              CPU: <b>{env.cpu_cores} cores</b>
            </Typography>
            <Typography variant="caption" color="text.secondary">
              RAM: <b>{env.ram_total_gb} GB</b>
              {env.ram_available_gb > 0 && <> (可用 ~{env.ram_available_gb.toFixed(0)} GB)</>}
            </Typography>
            {env.cuda_version && (
              <Typography variant="caption" color="text.secondary">
                CUDA: <b>{env.cuda_version}</b>
              </Typography>
            )}
            <Typography variant="caption" color="text.secondary">
              PyTorch: <b>{env.pytorch_version}</b>
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Python: <b>{env.python_version}</b>
            </Typography>
          </Box>
        </Card>
      )}

      {/* 三板块模型列表 */}
      {(["subtitle", "translate", "tts"] as const).map((cat) => {
        const catModels = grouped[cat] || [];
        const meta = CATEGORY_LABELS[cat];
        const isExpanded = expanded[cat];
        return (
          <Card key={cat} variant="outlined" sx={{ mb: 1 }}>
            <Box
              onClick={() => toggleCategory(cat)}
              sx={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                px: 1.5, py: 1, cursor: "pointer",
                "&:hover": { bgcolor: "action.hover" },
              }}
            >
              <Box display="flex" alignItems="center" gap={1}>
                <Typography variant="body2" fontWeight={600}>
                  {meta.icon} {meta.title}
                </Typography>
                <Chip size="small" label={`${catModels.length} 个模型`} variant="outlined" />
              </Box>
              {isExpanded ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
            </Box>

            <Collapse in={isExpanded}>
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.75rem" }}>模型</TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.75rem" }}>存储路径</TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.75rem" }}>功能</TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.75rem" }}>状态</TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.75rem" }}>适配</TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.75rem" }}>大小</TableCell>
                      <TableCell sx={{ fontWeight: 600, fontSize: "0.75rem" }}>操作</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {catModels.map((m) => (
                      <TableRow key={m.id}>
                        <TableCell>
                          <Typography variant="caption" fontWeight={500}>{m.name}</Typography>
                        </TableCell>
                        <TableCell>
                          <Tooltip title={`在资源管理器中打开: ${m.path}`}>
                            <Typography
                              variant="caption"
                              onClick={async () => {
                                try {
                                  await fetch("/api/files/open-path", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ path: m.path }),
                                  });
                                } catch { /* ignore */ }
                              }}
                              sx={{
                                fontFamily: "monospace",
                                fontSize: "0.65rem",
                                color: "primary.main",
                                cursor: "pointer",
                                textDecoration: "underline",
                                "&:hover": { color: "primary.dark" },
                              }}
                            >
                              {m.rel_path || m.path}
                            </Typography>
                          </Tooltip>
                        </TableCell>
                        <TableCell>
                          <Typography variant="caption" color="text.secondary">
                            {m.function}
                          </Typography>
                        </TableCell>
                        <TableCell>{statusChip(m)}</TableCell>
                        <TableCell>{fitChip(m)}</TableCell>
                        <TableCell>
                          <Typography variant="caption" color="text.secondary">
                            {m.size_gb > 0
                              ? m.exists && m.size_mb > 0
                                ? `${m.size_gb} GB (${m.size_mb.toFixed(0)} MB)`
                                : `${m.size_gb} GB`
                              : "—"}
                          </Typography>
                        </TableCell>
                        <TableCell>{actionCell(m)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Collapse>
          </Card>
        );
      })}
    </Box>
  );
}
