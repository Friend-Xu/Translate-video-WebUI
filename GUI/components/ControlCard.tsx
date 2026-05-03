import type { ReactNode } from 'react'
import { Box, Card, CardContent, Typography } from '@mui/material'

interface ControlCardProps {
  icon: ReactNode
  title: string
  subtitle: string
  children: ReactNode
}

export function ControlCard({ icon, title, subtitle, children }: ControlCardProps) {
  return (
    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ display: 'flex', gap: 2, flex: 1 }}>
        <Box sx={{ mt: 0.5 }}>
          <Box sx={{ p: 1, bgcolor: 'primary.light', borderRadius: 2, display: 'flex' }}>
            {icon}
          </Box>
        </Box>
        <Box sx={{ flex: 1 }}>
          <Typography variant="body1" fontWeight={600} color="text.primary">{title}</Typography>
          <Typography variant="caption" sx={{ minHeight: 32, display: 'block', mb: 1 }}>{subtitle}</Typography>
          {children}
        </Box>
      </CardContent>
    </Card>
  )
}
