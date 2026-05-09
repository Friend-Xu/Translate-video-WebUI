import { useState, useEffect } from 'react'
import {
  Dialog, DialogTitle, DialogContent, DialogActions,
  Button, TextField, Box, Typography, IconButton, Select, MenuItem,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import AddIcon from '@mui/icons-material/Add'

interface GlossaryTerm {
  key: string
  value: string
}

interface GlossaryEditorProps {
  open: boolean
  onClose: () => void
}

async function apiFetch(url: string, options?: RequestInit) {
  const resp = await fetch(url, options)
  if (!resp.ok) throw new Error(resp.statusText)
  return resp.json()
}

export function GlossaryEditor({ open, onClose }: GlossaryEditorProps) {
  const [dicts, setDicts] = useState<string[]>([])
  const [activeDict, setActiveDict] = useState('minecraft')
  const [terms, setTerms] = useState<GlossaryTerm[]>([])
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (open) {
      apiFetch('/api/glossary/dicts').then(data => {
        setDicts(data.dicts?.map((d: any) => d.name) ?? [])
      }).catch(() => {})
    }
  }, [open])

  useEffect(() => {
    if (open && activeDict) {
      setLoading(true)
      apiFetch(`/api/glossary/dict/${activeDict}`).then(data => {
        const t = data.terms || {}
        setTerms(Object.entries(t).map(([k, v]) => ({ key: k, value: String(v) })))
        setLoading(false)
      }).catch(() => setLoading(false))
    }
  }, [open, activeDict])

  function handleSave() {
    const obj = Object.fromEntries(terms.filter(t => t.key.trim()).map(t => [t.key.trim(), t.value.trim()]))
    apiFetch(`/api/glossary/dict/${activeDict}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description: '', terms: obj }),
    }).then(() => alert('Saved')).catch(e => alert('Error: ' + e.message))
  }

  function handleAdd() {
    if (!newKey.trim() || !newValue.trim()) return
    setTerms([...terms, { key: newKey.trim(), value: newValue.trim() }])
    setNewKey('')
    setNewValue('')
  }

  function handleDelete(key: string) {
    setTerms(terms.filter(t => t.key !== key))
  }

  function handleChange(index: number, field: 'key' | 'value', val: string) {
    const updated = [...terms]
    updated[index] = { ...updated[index], [field]: val }
    setTerms(updated)
  }

  function handleImport() {
    const input = prompt('Paste JSON:')
    if (!input) return
    try {
      const data = JSON.parse(input)
      const t = data.terms || data
      setTerms(Object.entries(t).map(([k, v]) => ({ key: k, value: String(v) })))
    } catch {
      alert('Invalid JSON')
    }
  }

  function handleExport() {
    const obj = Object.fromEntries(terms.map(t => [t.key, t.value]))
    navigator.clipboard.writeText(JSON.stringify({ name: activeDict, terms: obj }, null, 2))
    alert('Copied')
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Glossary Editor</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', mt: 1 }}>
          <Select size="small" value={activeDict} onChange={e => setActiveDict(e.target.value)}>
            {dicts.map(d => <MenuItem key={d} value={d}>{d}</MenuItem>)}
            <MenuItem value="__new__">+ New Dictionary</MenuItem>
          </Select>
          {activeDict === '__new__' && (
            <TextField size="small" placeholder="name" onBlur={e => {
              if (e.target.value) { setDicts([...dicts, e.target.value]); setActiveDict(e.target.value) }
            }} />
          )}
          <Button size="small" variant="outlined" onClick={handleImport}>Import</Button>
          <Button size="small" variant="outlined" onClick={handleExport}>Export</Button>
        </Box>
        {loading ? <Typography>Loading...</Typography> : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Source Term</TableCell>
                  <TableCell>Target</TableCell>
                  <TableCell width={60} />
                </TableRow>
              </TableHead>
              <TableBody>
                {terms.map((term, i) => (
                  <TableRow key={i}>
                    <TableCell>
                      <TextField size="small" fullWidth value={term.key}
                        onChange={e => handleChange(i, 'key', e.target.value)} />
                    </TableCell>
                    <TableCell>
                      <TextField size="small" fullWidth value={term.value}
                        onChange={e => handleChange(i, 'value', e.target.value)} />
                    </TableCell>
                    <TableCell>
                      <IconButton size="small" onClick={() => handleDelete(term.key)}><DeleteIcon /></IconButton>
                    </TableCell>
                  </TableRow>
                ))}
                <TableRow>
                  <TableCell>
                    <TextField size="small" fullWidth value={newKey}
                      onChange={e => setNewKey(e.target.value)} placeholder="New term" />
                  </TableCell>
                  <TableCell>
                    <TextField size="small" fullWidth value={newValue}
                      onChange={e => setNewValue(e.target.value)} placeholder="Translation" />
                  </TableCell>
                  <TableCell>
                    <IconButton size="small" onClick={handleAdd}><AddIcon /></IconButton>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </TableContainer>
        )}
        <Typography variant="caption" mt={2} display="block">{terms.length} terms</Typography>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave}>Save</Button>
      </DialogActions>
    </Dialog>
  )
}
