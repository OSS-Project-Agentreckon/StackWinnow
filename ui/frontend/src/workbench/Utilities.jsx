import { useEffect, useState } from 'react'
import { useWorkbench, download, requestFor } from './Context'
import { Badge, Empty, Heading, JsonDetails, Notice, NeedsProject, SectionTitle } from './Elements'
import { PlanReview, OperationResult } from './Manage'

export function Profiles() {
  const {settings, plan, setPlan, adoptProfilePlan, operation, setOperation, post, run, busy} = useWorkbench()
  const [text,setText] = useState('')
  async function readFile(event) {
    const file=event.target.files?.[0]
    if (!file) return
    await run('Reading profile',async()=>{
      if (file.size > 1024*1024) throw new Error('Choose a profile smaller than 1 MiB.')
      setText(await file.text())
    })
  }
  async function importProfile() {
    setPlan(null); setOperation(null)
    await run('Planning profile in this project',async()=>{
      let profile
      try {profile=JSON.parse(text)} catch {throw new Error('Profile must contain valid JSON.')}
      adoptProfilePlan(await post('profiles/import',{project_root:settings.project_root,profile}))
    })
  }
  return <><Heading eyebrow="REUSE / PORTABLE PROFILES" title="Bring your toolkit to the next project." description="Export supported choices or import a profile for a fresh destination review."/>
    <div className="panel"><SectionTitle title="Import a portable profile"/><p>Choose a profile JSON file or paste its contents. The project path above is the destination. Existing installation state and ownership are never copied.</p><label className="field"><span>Profile file</span><input type="file" accept=".json,application/json" onChange={readFile} disabled={!!busy}/></label><label className="field"><span>Profile JSON</span><textarea rows={10} value={text} onChange={e=>setText(e.target.value)} placeholder="Paste a StackWinnow portable profile here" disabled={!!busy}/></label><button className="button primary" onClick={importProfile} disabled={!!busy || !text.trim() || !settings.project_root}>Review destination plan</button></div>
    <Notice>To export a profile, prepare a setup plan in Manage tools, then choose Export profile. Freeform goals, credentials and local installation receipts are not exported.</Notice>
    {plan?.kind === 'workflow' && <PlanReview key={plan.plan_id}/>}<OperationResult operation={operation}/>
  </>
}
export function Reports() {
  const {settings, selected, run, post, busy} = useWorkbench()
  const [report,setReport] = useState(null)
  const [reportRoot,setReportRoot] = useState('')
  async function generate() {
    setReport(null)
    await run('Building project report',async()=>{setReport(await post('reports',requestFor(settings,selected)));setReportRoot(settings.project_root)})
  }
  return <><Heading eyebrow="SHARE / PROJECT REPORT" title="Keep the evidence with the decisions." description="Generate a fresh report containing inspection, source findings, recommendations, and compatibility notes."/>
    {!settings.project_root ? <NeedsProject/> : <><div className="panel report-intro"><div><h3>A project snapshot you can share</h3><p>Markdown for reading. JSON for further analysis. Generation rescans the current project; no tools are installed.</p></div><button className="button primary" disabled={!!busy} onClick={generate}>Generate report</button></div>
      {report && <div className="panel"><SectionTitle title="Generated report"><Badge tone="green">Ready to download</Badge></SectionTitle><p className="small muted">Snapshot: {reportRoot}</p><div className="action-row"><button className="button primary" onClick={()=>download('stackwinnow-report.md',report.markdown,'text/markdown')}>Download Markdown</button><button className="button secondary" onClick={()=>download('stackwinnow-report.json',report.json)}>Download JSON</button></div><pre className="report-preview">{report.markdown}</pre></div>}</>}
  </>
}
export function Environment() {
  const {settings, run, post, busy} = useWorkbench()
  const [result,setResult] = useState(null)
  useEffect(() => setResult(null), [settings.project_root])
  return <><Heading eyebrow="CHECK / ENVIRONMENT" title="Understand the machine behind the project." description="Inspect local runtime versions and compare them with supported mode requirements."/>
    {!settings.project_root ? <NeedsProject/> : <><div className="panel"><h3>Host prerequisites</h3><p>Reads the host platform, Python, Node and package-manager availability. A passing host check alone does not establish tool readiness.</p><button className="button primary" disabled={!!busy} onClick={()=>run('Checking local environment',async()=>setResult(await post('environment',{project_root:settings.project_root})))}>Inspect environment</button></div>
    {result && <><div className="panel"><SectionTitle title="Observed environment"/>{result.diagnostics.map((d,i)=><p className="diagnostic" key={i}><Badge tone={d.status==='succeeded'?'green':'amber'}>{d.status}</Badge>{d.message}</p>)}<JsonDetails value={result.profile}/></div><div className="panel"><h3>Exact managed-mode requirements</h3>{result.modes.map(m=><p key={m.tool_id}><strong>{m.tool_id}</strong> <span className="muted">{m.requirements.join(' · ')}</span></p>)}</div></>}
    {!result && <Empty title="No host check yet">Run the inspection to see actual runtime facts for this machine.</Empty>}</>}
  </>
}
