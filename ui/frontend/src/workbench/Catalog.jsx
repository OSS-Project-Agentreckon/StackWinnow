import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useWorkbench } from './Context'
import { ToolCard } from './Discovery'
import { Empty, Heading, Badge } from './Elements'
export default function Catalog() {
  const {catalog, meta, selected, settings} = useWorkbench()
  const [query,setQuery] = useState('')
  const [category,setCategory] = useState('')
  const [managed,setManaged] = useState(false)
  const tools = catalog.filter(t => (!category || category === t.category) && (!managed || t.managed_mode) && (t.name + ' ' + t.description).toLowerCase().includes(query.toLowerCase()))
  return <><Heading eyebrow="EXPLORE / TOOL CATALOG" title="Build a considered toolkit." description="Compare capabilities, evidence, license scope, and actual setup support."/>
    <div className="toolbar"><input aria-label="Search tools" placeholder="Search tools or capabilities…" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="Category" value={category} onChange={e=>setCategory(e.target.value)}><option value="">All categories</option>{meta?.categories.map(c=><option key={c}>{c}</option>)}</select><label className="check-label"><input type="checkbox" checked={managed} onChange={e=>setManaged(e.target.checked)}/>Managed modes only</label></div>
    <div className="catalog-summary"><span>{tools.length} tools <Badge>{meta?.modes.length || 0} managed modes</Badge></span><span className="small muted">Compatibility target: {settings.assistant || 'not selected'} / {settings.platform || 'not specified'}</span></div>
    <div className="tool-grid">{tools.map(t=><ToolCard key={t.tool_id} tool={t}/>)}</div>{!tools.length && <Empty title="No tools match these filters">Try another category or search term.</Empty>}
    {selected.length > 0 && <div className="selection-tray"><strong>{selected.length} tools selected</strong><Link className="button primary" to="/workflow">Review setup →</Link></div>}
  </>
}
