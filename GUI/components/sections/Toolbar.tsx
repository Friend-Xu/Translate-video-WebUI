import { Box, Typography, Card, Button, Stack } from '@mui/material'
import UploadFileIcon from '@mui/icons-material/UploadFileRounded'
import SubtitlesIcon from '@mui/icons-material/SubtitlesRounded'
import VideoLibraryIcon from '@mui/icons-material/VideoLibraryRounded'
import SettingsBackupRestoreIcon from '@mui/icons-material/SettingsBackupRestoreRounded'
import SaveAltIcon from '@mui/icons-material/SaveAltRounded'
import { SectionHeader } from '../SectionHeader'

interface ToolbarProps {
  onImportVideo: () => void
  onImportSubtitles: () => void
  onExportVideo: () => void
  onQuickConfig: () => void
  onSaveConfig: () => void
}

export function Toolbar({ onImportVideo, onImportSubtitles, onExportVideo, onQuickConfig, onSaveConfig }: ToolbarProps) {
  return (
    <>
      <SectionHeader title="工具栏与快捷按钮" />
      <Card sx={{ bgcolor: 'transparent', boxShadow: 'none', border: 'none' }}>
        <Box sx={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Box>
            <Typography variant="caption" display="block" mb={1} fontWeight={600}>文件操作快捷按钮</Typography>
            <Stack direction="row" spacing={2}>
              <Button variant="outlined" startIcon={<UploadFileIcon />} onClick={onImportVideo}>导入视频</Button>
              <Button variant="outlined" startIcon={<SubtitlesIcon />} onClick={onImportSubtitles}>导入字幕文件</Button>
              <Button variant="outlined" startIcon={<VideoLibraryIcon />} onClick={onExportVideo}>导出合成视频</Button>
            </Stack>
          </Box>
          <Box>
            <Typography variant="caption" display="block" mb={1} fontWeight={600}>设置快捷按钮</Typography>
            <Stack direction="row" spacing={2}>
              <Button variant="outlined" color="secondary" startIcon={<SettingsBackupRestoreIcon />} onClick={onQuickConfig}>快速配置</Button>
              <Button variant="outlined" color="secondary" startIcon={<SaveAltIcon />} onClick={onSaveConfig}>保存配置</Button>
            </Stack>
          </Box>
        </Box>
      </Card>
    </>
  )
}
