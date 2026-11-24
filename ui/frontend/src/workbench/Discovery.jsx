import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useWorkbench, requestFor } from './Context'
import { Badge, Heading, Empty, Icon, JsonDetails, Notice, SectionTitle } from './Elements'

export function ToolCard({tool, recommendation}) {
  const {selected, toggleTool, busy, settings, compatibilityReady} = useWorkbench()
  const [expanded, setExpanded] = useState(false)
  const reasons = recommendation?.reasons || []
  const assistantReasons = tool.eligibility?.reasons?.filter(r => r.code.startsWith('assistant')) || []
  return <article className={'tool-card' + (selected.includes(tool.tool_id) ? ' chosen' : '')}>
    <div className="tool-card-top"><span className="tool-monogram">{tool.name.slice(0,2)}</span><div><h3>{tool.name}</h3><span className="muted small">{tool.category}</span></div><Badge tone={tool.managed_mode ? 'green' : 'neutral'}>{tool.managed_mode ? 'Managed mode' : 'Catalog only'}</Badge></div>
    <p>{tool.description}</p>
    <div className="tags">{[...new Set(reasons.map(r => r.kind))].map(kind => <Badge key={kind} tone={kind === 'source' ? 'teal' : 'neutral'}>{{source:'Source evidence',goal:'Your goals',dependency:'Declared dependency',selection:'Selected'}[kind]}</Badge>)}</div>
    {reasons.length > 0 && <div className="match-preview"><span className="eyebrow">WHY IT FITS</span><p>{reasons[0].message}</p>{reasons[0].finding && <code>{reasons[0].finding.evidence[0].path}:{reasons[0].finding.evidence[0].line}</code>}</div>}
    <div className="compatibility"><span className="small">Target: <strong>{settings.assistant || 'not selected'}</strong></span><span className="small muted">{!compatibilityReady ? 'Refreshing compatibility for this target…' : assistantReasons.length ? assistantReasons[0].message : 'Catalog assistant compatibility documented.'}</span></div>
    <div className="tool-actions"><button className="text-button" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? 'Less detail' : 'Evidence & requirements'} <span>{expanded ? '−' : '+'}</span></button>{tool.managed_mode && <button className={'button small-button ' + (selected.includes(tool.tool_id) ? 'selected' : 'secondary')} disabled={!!busy} onClick={() => toggleTool(tool.tool_id)}>{selected.includes(tool.tool_id) ? '✓ Selected' : '+ Select'}</button>}</div>
    {expanded && <div className="tool-expanded">
      {reasons.map((r,i) => <div className="reason" key={i}><Badge>{r.kind}</Badge><p>{r.message}</p>{r.finding && <><div className="evidence-paths">{r.finding.evidence.map((e,j) => <code key={j}>{e.path}:{e.line}</code>)}</div><p className="question">{r.finding.question}</p>{r.finding.caveats.map((c,j) => <p className="small muted" key={j}>{c}</p>)}</>}</div>)}
      <h4>Setup requirements</h4><ul>{(tool.managed_mode?.requirements || tool.prerequisites || []).map((r,i) => <li key={i}>{r}</li>)}</ul>
      <h4>Catalog compatibility checks</h4><ul>{compatibilityReady && tool.eligibility?.reasons?.map((r,i) => <li key={i}>{r.message}</li>)}</ul>
      <h4>Limits & license scope</h4><p>{tool.license_scope}</p><ul>{tool.limitations?.map((l,i) => <li key={i}>{l}</li>)}</ul>
      {tool.alternatives?.length > 0 && <p>Alternatives: {tool.alternatives.join(', ')}</p>}
      {tool.repository && <a href={tool.repository} target="_blank" rel="noreferrer">Upstream repository ↗</a>}
    </div>}
  </article>
}
export function Findings({discovery}) {
  return <div className="findings-list">{discovery.findings.map((f,i) => <article className="finding" key={i}>
    <div className="finding-number">{String(i+1).padStart(2,'0')}</div><div><div className="finding-top"><h3>{f.summary}</h3><Badge tone={f.confidence === 'medium' ? 'teal' : 'amber'}>{f.confidence} confidence</Badge></div><div className="evidence-paths">{f.evidence.map((e,j) => <code key={j}>{e.path}:{e.line}</code>)}</div><p className="question">{f.question}</p>{f.caveats.length > 0 && <details><summary className="small muted">Context & caveats</summary>{f.caveats.map((c,j) => <p key={j} className="small muted">{c}</p>)}</details>}</div>
  </article>)}</div>
}
export default function Discovery() {
  const {scan, settings, catalog, selected, busy} = useWorkbench()
  const [tab, setTab] = useState('opportunities')
  const [filter, setFilter] = useState('all')
  const result = scan?.result
  const source = result?.inspection.source_discovery
  const request = requestFor(settings)
  const changed = scan && ['project_root','goals','model_preference','config_path','scan_source'].some(k => JSON.stringify(scan.request[k]) !== JSON.stringify(request[k]))
  const recommendations = result?.recommendations.filter(t => filter === 'all' || t.reasons.some(r => r.kind === filter)) || []
  return <>
    <Heading eyebrow="DISCOVER / UNDERSTAND / IMPROVE" title="Find the opportunities in your code." description="Inspect your source, understand the evidence, and choose the tools that fit."/>
    {!result ? <>
      <div className="intro-panel"><div><Badge tone="teal">SOURCE-LED DISCOVERY</Badge><h2>Your code is the starting point.</h2><p>Choose a project above. StackWinnow scans supported files recursively, follows recognizable AI call patterns, and explains opportunities with evidence you can inspect.</p><div className="intro-steps"><span><b>01</b> Scan source</span><Icon name="arrow" size={16}/><span><b>02</b> Review evidence</span><Icon name="arrow" size={16}/><span><b>03</b> Choose tools</span></div></div><div className="code-preview"><div className="code-top"><i/><i/><i/><span>your-project / app.py</span></div><pre><span className="code-comment"># Opportunities begin with source evidence</span>{'\n'}for document in retrieved_documents:{'\n'}    response = client.responses.create({'\n'}        model=model, input=document{'\n'}    )</pre><div className="code-note"><Icon name="scan" size={17}/>Review call volume and context size</div></div></div>
      <div className="feature-grid">{[['files','See scan coverage','Inspect each scanned file, exclusions, and unsupported file types.'],['scan','Understand the why','Every finding has locations, confidence, and a question to validate.'],['workflow','Act on your choices','Review setup, verify tools, export profiles, and manage removal.']].map(([icon,title,text]) => <div className="feature" key={title}><Icon name={icon}/><h3>{title}</h3><p>{text}</p></div>)}</div>
    </> : <>
      {changed && <Notice tone="amber">Scan inputs have changed. These findings belong to the previous scan; rescan to refresh. Compatibility targets update independently.</Notice>}
      {!result.complete && <Notice tone="amber">Inspection is partial. Valid findings are shown below; check source coverage and diagnostics for skipped inputs.</Notice>}
      <div className="stat-grid">{[[source.files_scanned,'Source files analyzed'],[source.model_calls ?? '—','Recognized model calls'],[source.findings.length,'Source opportunities'],[result.recommendations.length,'Tool matches']].map(([n,label]) => <div className="stat" key={label}><strong>{n}</strong><span>{label}</span></div>)}</div>
      <div className="scan-summary"><span><span className="live-dot"/>{source.status === 'complete' ? 'Supported scan completed' : source.status === 'not-scanned' ? 'Source scan disabled' : 'Partial source coverage'} · {Object.entries(source.languages || {}).map(([k,v]) => k + ' ' + v).join(' / ') || 'See file coverage'}</span><Link to="/inspect">Explore file coverage <Icon name="arrow" size={15}/></Link></div>
      {source.findings.length === 0 && <Notice>{source.status === 'not-scanned' ? 'Source analysis was disabled for this scan. Enable Source + declarations in scan options.' : source.files_scanned === 0 ? 'No supported source files were analyzed. Check the chosen directory, ignore rules, file types and scan diagnostics.' : 'Source files were analyzed, but no supported opportunity patterns matched. Wrappers, other languages, and indirect model calls may need additional analysis.'} Dependency and goal matches remain labeled separately below.</Notice>}
      <div className="tabs"><button className={tab === 'opportunities' ? 'active' : ''} onClick={() => setTab('opportunities')}>Source opportunities <span>{source.findings.length}</span></button><button className={tab === 'tools' ? 'active' : ''} onClick={() => setTab('tools')}>Recommended tools <span>{result.recommendations.length}</span></button><button className={tab === 'facts' ? 'active' : ''} onClick={() => setTab('facts')}>Declarations & notes</button></div>
      {tab === 'opportunities' && (source.findings.length ? <Findings discovery={source}/> : <Empty title="No source opportunities matched">A completed scan is not proof that the project has no optimization opportunities. Review coverage for what was analyzed.</Empty>)}
      {tab === 'tools' && <><div className="toolbar"><SectionTitle title="Tools to consider" count={recommendations.length}/><select aria-label="Filter recommendation basis" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All match types</option><option value="source">From source evidence</option><option value="goal">From goals</option><option value="dependency">Declared dependencies</option></select></div><div className="tool-grid">{recommendations.map(r => <ToolCard key={r.tool_id} tool={catalog.find(t => t.tool_id === r.tool_id) || r} recommendation={r}/>)}</div>{!recommendations.length && <Empty title="No matches in this view">Try another match type, or browse the catalog.</Empty>}</>}
      {tab === 'facts' && <div className="panel"><SectionTitle title="Declared project metadata"/><dl className="facts">{Object.entries(result.inspection.profile.facts).map(([k,v]) => <div key={k}><dt>{k}</dt><dd>{v.join(', ') || '(explicitly empty)'}</dd></div>)}</dl><h3>Inspection diagnostics</h3>{result.inspection.diagnostics.map((d,i) => <p key={i} className="diagnostic"><Badge>{d.status}</Badge>{d.message}</p>)}{[...source.diagnostics,...result.notes].map((n,i) => <p key={i} className="small muted">{n}</p>)}{result.unmatched_goals.length > 0 && <Notice tone="amber">Unmatched goals: {result.unmatched_goals.join(', ')}</Notice>}<JsonDetails value={result}/></div>}
      <p className="footnote">Static evidence suggests what to investigate. It does not establish runtime savings or full project understanding.</p>
    </>}
    {selected.length > 0 && <div className="selection-tray"><span><strong>{selected.length} tools selected</strong><small>{selected.join(' · ')}</small></span><Link className={'button primary' + (busy ? ' disabled' : '')} to="/workflow">Review setup <Icon name="arrow" size={17}/></Link></div>}
  </>
}
