import { Box, Typography, IconButton, Tooltip, Divider } from '@mui/material'
import HomeIcon from '@mui/icons-material/HomeOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import SaveIcon from '@mui/icons-material/SaveOutlined'
import SettingsIcon from '@mui/icons-material/SettingsOutlined'
import ArticleIcon from '@mui/icons-material/ArticleOutlined'
import BuildIcon from '@mui/icons-material/BuildOutlined'

interface SidebarProps {
  activeTab: string
  onTabChange: (tab: string) => void
}

const menuItems = [
  { icon: <HomeIcon />, label: '主界面' },
  { icon: <TuneIcon />, label: '步骤配置' },
  { icon: <SaveIcon />, label: '输出设置' },
  { icon: <SettingsIcon />, label: '高级设置' },
  { icon: <ArticleIcon />, label: '日志与反馈' },
  { icon: <BuildIcon />, label: '工具栏' },
]

export function Sidebar({ activeTab, onTabChange }: SidebarProps) {
  return (
    <Box sx={{
      width: 80,
      bgcolor: 'background.paper',
      borderRight: '1px solid',
      borderColor: 'divider',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      py: 3,
      gap: 3,
      flexShrink: 0,
    }}>
      <Box sx={{ width: 40, height: 40, bgcolor: 'primary.main', borderRadius: 3, display: 'flex', justifyContent: 'center', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" color="white" fontWeight={800}>V</Typography>
      </Box>
      <Divider flexItem sx={{ mx: 2 }} />
      {menuItems.map((item) => {
        const isActive = activeTab === item.label
        return (
          <Tooltip title={item.label} placement="right" key={item.label}>
            <IconButton
              onClick={() => onTabChange(item.label)}
              aria-label={item.label}
              sx={{
                flexDirection: 'column',
                color: isActive ? 'primary.main' : 'text.secondary',
                bgcolor: isActive ? 'primary.light' : 'transparent',
                borderRadius: 3,
                p: 1.5,
                '&:hover': { bgcolor: 'primary.light', color: 'primary.main' },
                transition: 'all 0.2s',
              }}
            >
              {item.icon}
              <Typography variant="caption" sx={{ fontSize: '0.65rem', mt: 0.5, fontWeight: isActive ? 600 : 400 }}>
                {item.label}
              </Typography>
            </IconButton>
          </Tooltip>
        )
      })}
    </Box>
  )
}
