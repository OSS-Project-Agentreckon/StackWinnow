import { useEffect, useState } from 'react'
import { useWorkbench, download } from './Context'
import { Badge, Heading, JsonDetails, Notice, NeedsProject, SectionTitle, CopyButton } from './Elements'

export function OperationResult({operation}) {
  if (!operation) return null
  const data = operation.data
  const verification = data.verification || (data.tools ? data : null)
  const tone = data.ready || data.status === 'succeeded' ? 'green' : data.status === 'failed' ? 'amber' : 'neutral'
  return <section className="panel"><SectionTitle title={operation.title}><Badge tone={tone}>{data.dry_run ? 'Dry run' : data.status || 'Result'}</Badge></SectionTitle>
    {data.message && <p>{data.message}</p>}
    {data.outcomes?.map((o,i)=><p className="diagnostic" key={i}><Badge tone={o.status === 'succeeded' ? 'green' : 'amber'}>{o.status}</Badge><strong>{o.phase}</strong> {o.message}</p>)}
    {verification?.tools?.map(tool=><div className="verification-tool" key={tool.tool_id}><h3>{tool.tool_id}</h3>{tool.checks.map((c,i)=><div className="verification-check" key={i}><Badge tone={c.status === 'succeeded' ? 'green' : c.status === 'blocked' || c.status === 'failed' ? 'amber' : 'neutral'}>{c.status}</Badge><strong>{c.kind}</strong><span>{c.message}</span></div>)}</div>)}
    {data.removed_paths?.length > 0 && <p>Removed: {data.removed_paths.join(', ')}</p>}
    {data.retained_paths?.length > 0 && <p>Retained: {data.retained_paths.join(', ')}</p>}
    <JsonDetails value={data}/>
  </section>
}
export function PlanReview() {
  const {plan, setPlan, busy, post, run, setOperation} = useWorkbench()
  const [confirmed,setConfirmed] = useState(false)
  const attempted = plan?.attempted || false
  if (!plan) return null
  const doc = plan.document
  const removal = plan.kind === 'removal'
  const tools = removal ? doc.tool_ids : doc.request.selections.map(s=>s.tool_id)
  async function apply(dryRun) {
    if (!dryRun) {setPlan({...plan,attempted:true});setConfirmed(false)}
    await run(dryRun ? 'Validating reviewed plan' : removal ? 'Applying reviewed removal' : 'Applying reviewed workflow', async () => {
      const data = await post(removal ? 'removal/apply' : 'workflow/apply', {plan_id:plan.plan_id,confirm:!dryRun,dry_run:dryRun})
      setOperation({title:dryRun ? 'Plan validation' : removal ? 'Removal result' : 'Workflow result',data})
    })
  }
  async function exportProfile() {
    await run('Exporting portable profile',async()=>download('stackwinnow-profile.json',await post('profiles/export',{plan_id:plan.plan_id})))
  }
  return <section className="panel review-panel"><SectionTitle title={removal ? 'Review removal plan' : 'Review setup plan'}><Badge tone={attempted ? 'neutral' : 'teal'}>{attempted ? 'Attempt submitted — see result' : 'Prepared · not applied'}</Badge></SectionTitle>
    <p className="small muted">Project: <code>{doc.project_root}</code></p><div className="tags">{tools.map(t=><Badge key={t}>{t}</Badge>)}</div>
    {plan.phases.length > 0 && <ol className="phase-list">{plan.phases.map((p,i)=><li key={p}><span>{i+1}</span>{p}</li>)}</ol>}
    {!removal && <>{['headroom','promptfoo','playwright','graphify'].filter(k=>doc[k]).map(k=><div key={k} className="review-tool"><h4>{k === 'playwright' ? 'playwright-mcp' : k}</h4>{doc[k].installation?.steps?.map((step,i)=><div key={i} className="cli-step"><p className="small">{step.description || step.step_id}</p>{step.step_id && step.description && <div className="cli-command"><pre><code>{step.step_id}</code></pre><CopyButton text={step.step_id}/></div>}</div>)}<JsonDetails value={doc[k]} label="Commands, configuration & prerequisites"/></div>)}{doc.graphify_configuration && <JsonDetails value={doc.graphify_configuration} label="Graphify client configuration changes"/>}</>}
    {removal && <><div className="table-panel"><table><thead><tr><th>Runtime path</th><th>Action</th><th>Reason</th></tr></thead><tbody>{doc.runtimes.map((r,i)=><tr key={i}><td><code>{r.path}</code></td><td><Badge tone={r.action === 'remove' ? 'amber' : 'neutral'}>{r.action}</Badge></td><td>{r.reason}</td></tr>)}</tbody></table></div><p className="small">Retained paths: {doc.retained_paths.join(', ') || 'None listed'}</p><JsonDetails value={doc.configuration} label="Configuration restoration preview"/></>}
    <div className="action-row"><button className="button secondary" onClick={()=>download(removal ? 'removal-plan.json' : 'workflow-plan.json',doc)}>Download plan</button>{!removal && <button className="button secondary" onClick={exportProfile} disabled={!!busy}>Export profile</button>}<button className="button secondary" onClick={()=>apply(true)} disabled={!!busy || attempted}>Validate dry run</button></div>
    <JsonDetails value={doc} label="Full reviewed plan"/>
    <div className="apply-box"><p>{removal ? 'Applying restores owned configuration and removes only the reviewed managed resources.' : 'Applying may download packages, update owned project configuration, and run local functional checks.'} This exact plan is valid for one attempt; changed project state requires replanning.</p><label className="check-label"><input type="checkbox" checked={confirmed} disabled={!!busy || attempted} onChange={e=>setConfirmed(e.target.checked)}/>I reviewed the plan for this project and want to {removal ? 'remove these resources' : 'apply these changes'}.</label><button className={'button ' + (removal ? 'danger' : 'primary')} disabled={!confirmed || !!busy || attempted} onClick={()=>apply(false)}>{attempted ? 'Attempted — generate a fresh plan to retry' : removal ? 'Apply reviewed removal' : 'Apply reviewed setup'}</button></div>
  </section>
}
export default function Manage() {
  const {settings, selected, toggleTool, meta, plan, setPlan, operation, setOperation, post, run, busy} = useWorkbench()
  const [expectation,setExpectation] = useState({caller_file:'',caller_label:'',callee_file:'',callee_label:''})
  useEffect(() => setExpectation((plan?.document.project_root === settings.project_root && plan?.document.request?.expectation) || {caller_file:'',caller_label:'',callee_file:'',callee_label:''}), [settings.project_root])
  const [confirmCheck,setConfirmCheck] = useState(false)
  useEffect(() => setConfirmCheck(false), [selected])
  const hasGraph = selected.includes('graphify')
  const graphReady = !hasGraph || Object.values(expectation).every(v=>v.trim())
  const base = {project_root:settings.project_root,tool_ids:selected}
  async function prepare(removal) {
    setPlan(null); setOperation(null)
    await run(removal ? 'Planning removal' : 'Preparing workflow plan',async()=>{
      const data = await post(removal ? 'removal/plan' : 'workflow/plan',removal ? base : {...base, goals:[...settings.goals],model_preference:settings.model_preference,expectation:hasGraph ? expectation : null})
      setPlan(data)
    })
  }
  async function check(functional) {
    setConfirmCheck(false)
    await run(functional ? 'Running functional checks' : 'Reading managed status',async()=>setOperation({title:functional?'Fresh functional checks':'Passive project status',data:await post(functional?'workflow/check':'workflow/status',{...base,...(functional?{confirm:true}:{})})}))
  }
  return <><Heading eyebrow="CHOOSE / REVIEW / MANAGE" title="Turn decisions into a working setup." description="Select supported modes, review exact changes, then apply and verify them."/>
    {!settings.project_root ? <NeedsProject/> : <>
      <div className="mode-grid">{meta?.modes.map(m=><label className={'mode-card'+(selected.includes(m.tool_id)?' chosen':'')} key={m.tool_id}><div><input type="checkbox" checked={selected.includes(m.tool_id)} disabled={!!busy} onChange={()=>toggleTool(m.tool_id)}/><strong>{m.tool_id}</strong><Badge>{m.mode}</Badge></div><p>{m.description}</p><span className="small muted">v{m.version} · {m.requirements.join(' · ')}</span></label>)}</div>
      {settings.assistant && settings.assistant !== 'codex' && <Notice tone="amber">Your catalog target is {settings.assistant}. The managed Graphify and Playwright client integrations currently configure Codex; they do not configure {settings.assistant}. Review each mode before selecting.</Notice>}
      {hasGraph && <div className="panel"><h3>Graphify relationship to verify</h3><p className="small muted">Identify a known call relationship in this project. Both source files must exist. This gives the index and client checks a concrete expected result.</p><div className="field-grid">{Object.entries(expectation).map(([k,v])=><div className="field" key={k}><label htmlFor={k}>{k.replace('_',' ')}</label><input id={k} value={v} disabled={!!busy} placeholder={k.endsWith('file')?'src/app.py':'function_name'} onChange={e=>{setExpectation({...expectation,[k]:e.target.value});setPlan(null)}}/></div>)}</div></div>}
      <div className="panel"><SectionTitle title="Choose an action" count={selected.length}/><div className="action-row"><button className="button primary" disabled={!!busy || !selected.length || !graphReady} onClick={()=>prepare(false)}>Prepare setup plan</button><button className="button secondary" disabled={!!busy || !selected.length} onClick={()=>check(false)}>Read status</button><button className="button secondary" disabled={!!busy || !selected.length} onClick={()=>prepare(true)}>Plan removal</button></div><p className="small muted">Planning and status are read-only. Catalog entries without a registered mode cannot be installed here.</p><div className="functional-controls"><label className="check-label"><input type="checkbox" checked={confirmCheck} disabled={!!busy} onChange={e=>setConfirmCheck(e.target.checked)}/>Run fresh functional checks for the selected tools (may execute tools and write verification evidence).</label><button className="button secondary" disabled={!confirmCheck || !!busy || !selected.length} onClick={()=>check(true)}>Run functional checks</button></div></div>
      {plan && <PlanReview key={plan.plan_id}/>}<OperationResult operation={operation}/>
    </>}
  </>
}
