import { useRef } from 'react'
import { Box, Typography, Card, Button, Stack } from '@mui/material'
import UploadFileIcon from '@mui/icons-material/UploadFileRounded'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHighRounded'
import VideoLibraryIcon from '@mui/icons-material/VideoLibraryRounded'
import SettingsBackupRestoreIcon from '@mui/icons-material/SettingsBackupRestoreRounded'
import SaveAltIcon from '@mui/icons-material/SaveAltRounded'
import RateReviewIcon from '@mui/icons-material/RateReviewOutlined'
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined'
import FileOpenOutlinedIcon from '@mui/icons-material/FileOpenOutlined'
import { SectionHeader } from '../SectionHeader'

interface ToolbarProps {
  onImportVideo: () => void
  onOptimizeSubtitles: () => void
  onReviewSubtitles: () => void
  onExportVideo: () => void
  onQuickConfig: () => void
  onSaveConfig: () => void
  onExportConfig: () => void
  onImportConfig: (file: File) => void
}

export function Toolbar({ onImportVideo, onOptimizeSubtitles, onReviewSubtitles, onExportVideo, onQuickConfig, onSaveConfig, onExportConfig, onImportConfig }: ToolbarProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      onImportConfig(file)
    }
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  return (
    <>
      <SectionHeader title="工具栏与快捷按钮" />
      <Card sx={{ bgcolor: 'transparent', boxShadow: 'none', border: 'none' }}>
        <Box sx={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Box>
            <Typography variant="caption" display="block" mb={1} fontWeight={600}>文件操作快捷按钮</Typography>
            <Stack direction="row" spacing={2}>
              <Button variant="outlined" startIcon={<UploadFileIcon />} onClick={onImportVideo}>导入视频</Button>
              <Button variant="outlined" startIcon={<AutoFixHighIcon />} onClick={onOptimizeSubtitles}>优化外挂字幕</Button>
              <Button variant="outlined" startIcon={<RateReviewIcon />} onClick={onReviewSubtitles}>字幕校准</Button>
              <Button variant="outlined" startIcon={<VideoLibraryIcon />} onClick={onExportVideo}>导出合成视频</Button>
            </Stack>
          </Box>
          <Box>
            <Typography variant="caption" display="block" mb={1} fontWeight={600}>设置快捷按钮</Typography>
            <Stack direction="row" spacing={2}>
              <Button variant="outlined" color="secondary" startIcon={<SettingsBackupRestoreIcon />} onClick={onQuickConfig}>快速配置</Button>
              <Button variant="outlined" color="secondary" startIcon={<SaveAltIcon />} onClick={onSaveConfig}>保存配置</Button>
              <Button variant="outlined" color="secondary" startIcon={<FileDownloadOutlinedIcon />} onClick={onExportConfig}>导出配置</Button>
              <Button variant="outlined" color="secondary" startIcon={<FileOpenOutlinedIcon />} onClick={handleImportClick}>导入配置</Button>
            </Stack>
          </Box>
        </Box>
      </Card>
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        style={{ display: 'none' }}
        onChange={handleFileChange}
      />
    </>
  )
}
