import { Box, Typography } from '@mui/material'

interface Props {
  name: string
  role?: string
}

export default function RegionPlaceholder({ name, role }: Props) {
  return (
    <Box
      role={role}
      sx={{
        height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
        bgcolor: 'grey.100', border: '2px dashed', borderColor: 'grey.300',
        borderRadius: 2, m: 1,
      }}
    >
      <Typography variant="body2" color="text.secondary">
        {name}
      </Typography>
    </Box>
  )
}
