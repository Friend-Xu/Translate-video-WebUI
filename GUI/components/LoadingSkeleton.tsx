import { Box, Skeleton, Typography } from '@mui/material'

interface Props {
  type: 'timeline' | 'inspector' | 'dock' | 'pulse'
}

const CONFIG = {
  timeline: { label: '时间轴加载中...', blocks: 8, h: 40 },
  inspector: { label: '事件详情加载中...', blocks: 4, h: 20 },
  dock: { label: '日志加载中...', blocks: 3, h: 16 },
  pulse: { label: '', blocks: 1, h: 24 },
} as const

export default function LoadingSkeleton({ type }: Props) {
  const cfg = CONFIG[type]
  return (
    <Box sx={{ p: 2, height: '100%' }}>
      {cfg.label && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {cfg.label}
        </Typography>
      )}
      {Array.from({ length: cfg.blocks }).map((_, i) => (
        <Skeleton key={i} variant="rounded" height={cfg.h}
          sx={{ mb: 1, opacity: 1 - i * 0.08 }} animation="wave" />
      ))}
    </Box>
  )
}

export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <Box sx={{
      position: 'fixed', top: 48, left: 0, right: 0, zIndex: 3000,
      bgcolor: 'error.main', color: 'common.white', px: 2, py: 1,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    }}>
      <Typography variant="body2">{message}</Typography>
      {onDismiss && (
        <Box component="button" onClick={onDismiss} aria-label="关闭错误提示"
          sx={{ bg: 'none', border: 'none', color: 'common.white', cursor: 'pointer', fontSize: '1rem' }}>
          ✕
        </Box>
      )}
    </Box>
  )
}

export function EmptyState({ icon, title, subtitle }: { icon?: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <Box sx={{
      height: '100%', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', p: 4, textAlign: 'center',
    }}>
      {icon && <Box sx={{ mb: 2, opacity: 0.4 }}>{icon}</Box>}
      <Typography variant="h6" color="text.secondary" sx={{ fontWeight: 500, mb: 0.5 }}>
        {title}
      </Typography>
      {subtitle && <Typography variant="body2" color="text.disabled">{subtitle}</Typography>}
    </Box>
  )
}
