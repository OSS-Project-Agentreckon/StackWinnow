import { NavLink, useLocation } from 'react-router-dom'
import { useState } from 'react'
import { useWorkbench } from './Context'
import { Badge, Icon, Notice } from './Elements'
const pages = [
  ['/recommend', 'Discovery', 'scan'], ['/inspect', 'Source coverage', 'files'], ['/catalog', 'Tool catalog', 'catalog'],
  ['/workflow', 'Manage tools', 'workflow'], ['/profiles', 'Portable profiles', 'profiles'], ['/reports', 'Project report', 'reports'], ['/environment', 'Environment', 'environment'],
]
export default function Shell({children}) {
  const {settings, update, scanProject, busy, connection, meta, error, setError, selected, scan} = useWorkbench()
  const [options, setOptions] = useState(false)
  const location = useLocation()
  const title = pages.find(p => p[0] === location.pathname)?.[1] || 'Workspace'
  return <div className="workbench">
    <aside className="sidebar">
      <NavLink className="brand" to="/recommend"><span className="brand-mark"><Icon name="scan" size={25}/></span><span>StackWinnow<small>PROJECT WORKBENCH</small></span></NavLink>
      <div className="nav-label">WORKSPACE</div>
      <nav>{pages.map(([to,label,icon]) => <NavLink key={to} to={to} className={({isActive}) => 'nav-item' + (isActive ? ' active' : '')}><Icon name={icon}/>{label}{to === '/workflow' && selected.length > 0 && <span className="nav-count">{selected.length}</span>}</NavLink>)}</nav>
      <div className="sidebar-note"><span className="live-dot"/> Local by design<p>Source stays on your machine.<br/>Discovery makes no model calls.</p><span className="version">{meta?.version || 'Connecting…'}</span></div>
    </aside>
    <div className="workspace-main">
      <div className="topbar"><span>Workspace <span className="crumb">/</span> <strong>{title}</strong></span><Badge tone={connection === 'ready' ? 'green' : 'amber'}>{connection === 'ready' ? 'Local engine connected' : connection === 'outdated' ? 'Backend update needed' : connection === 'offline' ? 'Backend offline' : 'Connecting'}</Badge></div>
      <div className="project-bar">
        <form onSubmit={e => {e.preventDefault(); scanProject()}}>
          <label htmlFor="project-path">PROJECT DIRECTORY</label>
          <div className="project-input-row"><div className="path-input"><Icon name="files" size={18}/><input id="project-path" required value={settings.project_root} onChange={e => update('project_root',e.target.value)} placeholder="/path/to/your/project" disabled={!!busy}/></div>
          <button type="button" className={'button secondary' + (options ? ' selected' : '')} onClick={() => setOptions(!options)} aria-expanded={options}>Scan options{(settings.goals || settings.assistant || !settings.scan_source || settings.config_path) && <span className="option-dot"/>}</button>
          <button className="button primary" disabled={!!busy || connection !== 'ready'}><Icon name="scan" size={17}/>{busy.startsWith('Scanning') ? 'Scanning…' : scan ? 'Rescan project' : 'Scan project'}</button></div>
        </form>
        <div className="scan-caption"><span>{settings.scan_source ? 'Recursive source analysis + project declarations' : 'Declarations only — source scan is disabled'}</span><span>{scan ? 'Last scan ' + scan.at : 'No goals required'}</span></div>
        {options && <div className="options-panel">
          <div className="field"><label htmlFor="scope">Inspection scope</label><select id="scope" value={settings.scan_source ? 'source' : 'declarations'} disabled={!!busy} onChange={e => update('scan_source', e.target.value === 'source')}><option value="source">Source + declarations</option><option value="declarations">Declarations only</option></select><small>Python, JavaScript and TypeScript. Other file types are listed in coverage.</small></div>
          <div className="field"><label htmlFor="target-assistant">Coding assistant target</label><select id="target-assistant" value={settings.assistant} disabled={!!busy} onChange={e => update('assistant',e.target.value)}><option value="">No target selected</option>{meta?.assistants.map(a => <option key={a} value={a}>{a}</option>)}</select><small>Updates catalog compatibility. It does not choose an analysis model. Managed client setup targets Codex.</small></div>
          <div className="field"><label htmlFor="target-platform">Compatibility platform</label><select id="target-platform" value={settings.platform} disabled={!!busy} onChange={e => update('platform',e.target.value)}><option value="">Not specified</option>{meta?.platforms.map(p => <option key={p}>{p}</option>)}</select></div>
          <div className="field"><label htmlFor="priorities">Optional goals</label><input id="priorities" value={settings.goals} disabled={!!busy} onChange={e => update('goals',e.target.value)} placeholder="Reduce costs, evaluate answers"/><small>Comma-separated priorities refine recommendations on the next scan.</small></div>
          <div className="field"><label htmlFor="model-pref">Model preference</label><select id="model-pref" value={settings.model_preference} disabled={!!busy} onChange={e => update('model_preference',e.target.value)}>{['any','local','hosted'].map(p => <option key={p}>{p}</option>)}</select><small>Recorded intent; model support is not verified by the catalog.</small></div>
          <div className="field"><label htmlFor="config-path">Optional MCP configuration</label><input id="config-path" value={settings.config_path} disabled={!!busy} onChange={e => update('config_path',e.target.value)} placeholder=".cursor/mcp.json"/><small>Project-relative JSON. Only registered server names are inspected.</small></div>
        </div>}
      </div>
      <main>
        {connection === 'outdated' && <Notice tone="amber">The UI requires workbench API v2. Restart the backend from this checkout, then refresh this page.</Notice>}
        {connection === 'offline' && <Notice tone="amber">The backend is unavailable. Start it with the documented UI launcher, then refresh.</Notice>}
        {error && <div className="error-banner" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
        {busy && <div className="activity" role="status"><span className="spinner"/>{busy}…</div>}
        {children}
      </main>
    </div>
  </div>
}
