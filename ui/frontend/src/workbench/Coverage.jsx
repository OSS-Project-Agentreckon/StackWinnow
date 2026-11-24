import { useState } from 'react'
import { useWorkbench } from './Context'
import { Badge, Empty, Heading, JsonDetails, Notice, ScanLink } from './Elements'
export default function Coverage() {
  const {scan, meta} = useWorkbench()
  const [query,setQuery] = useState('')
  const [status,setStatus] = useState('all')
  const source = scan?.result.inspection.source_discovery
  const files = source?.files || []
  const shown = files.filter(f => (status === 'all' || f.status === status) && f.path.toLowerCase().includes(query.toLowerCase()))
  return <>
    <Heading eyebrow="PROJECT / SOURCE COVERAGE" title="Know exactly what was inspected." description="A file-level record of source analysis, exclusions, and unsupported formats."/>
    {!source ? <Empty title="Run a project scan first" action={<ScanLink/>}>Your scan will appear here, including files with no detected AI patterns.</Empty> : <>
      <div className="stat-grid">{[[source.files_scanned,'Analyzed files'],[source.excluded_entries,'Excluded entries'],[source.unsupported_files,'Other file types'],[(source.bytes_scanned / 1024).toFixed(1) + ' KB','Source read']].map(([n,t]) => <div className="stat" key={t}><strong>{n ?? '—'}</strong><span>{t}</span></div>)}</div>
      <Notice>Source inspection is recursive for {meta?.scan.extensions.join(', ')}. Declarations such as requirements.txt and pyproject.toml are read separately. Excluded directories are not traversed, so their entry counts are not file totals.</Notice>
      {source.status === 'not-scanned' && <Notice tone="amber">Source scanning was disabled. Enable it in Scan options and rescan.</Notice>}
      {source.inventory_truncated && <Notice tone="amber">The file ledger reached its display limit. Scan totals may exceed the listed entries.</Notice>}
      <div className="toolbar"><input aria-label="Search source paths" placeholder="Filter by path…" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="File status" value={status} onChange={e=>setStatus(e.target.value)}>{['all','scanned','excluded','unsupported','error'].map(s=><option key={s}>{s}</option>)}</select><span className="muted small">{shown.length} entries</span></div>
      <div className="table-panel"><table><thead><tr><th>Project-relative path</th><th>Status</th><th>Language</th><th>AI calls</th><th>Details</th></tr></thead><tbody>{shown.map((f,i)=><tr key={i}><td><code>{f.path}</code></td><td><Badge tone={f.status === 'scanned' ? 'green' : f.status === 'error' ? 'amber' : 'neutral'}>{f.status}</Badge></td><td>{f.language || '—'}</td><td>{f.status === 'scanned' ? f.model_calls : '—'}</td><td className="small muted">{f.reason}</td></tr>)}</tbody></table>{!shown.length && <Empty title="No files in this view">Change the filter or review the scan diagnostics below.</Empty>}</div>
      <div className="panel"><h3>Limits & diagnostics</h3><p className="small muted">Up to {meta?.scan.max_files} source files; {(meta?.scan.max_file_bytes / 1024) || 256} KiB per file. Coverage: {source.status}.</p>{[...source.diagnostics,...source.limitations].map((d,i)=><p key={i} className="small muted">{d}</p>)}<JsonDetails value={source}/></div>
    </>}
  </>
}
