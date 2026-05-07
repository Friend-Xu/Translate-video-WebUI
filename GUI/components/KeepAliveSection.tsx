import { Box } from '@mui/material'

interface KeepAliveSectionProps {
  active: boolean
  children: React.ReactNode
}

export function KeepAliveSection({ active, children }: KeepAliveSectionProps) {
  return <Box sx={{ display: active ? undefined : 'none', flex: active ? '1 1 auto' : undefined }}>{children}</Box>
}
