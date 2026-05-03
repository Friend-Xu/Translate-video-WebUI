import { Typography } from '@mui/material'

export function SectionHeader({ title }: { title: string }) {
  return (
    <Typography variant="h6" color="primary.main" sx={{ mt: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
      {title}
    </Typography>
  )
}
