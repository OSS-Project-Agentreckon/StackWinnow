import { useState, useRef } from 'react'
import axios from 'axios'
import { useWorkbench } from './Context'
import { Badge, Heading, NeedsProject, Notice, SectionTitle } from './Elements'

const CATEGORY_ORDER = ['observability', 'evaluation', 'context', 'model-gateway']
const CATEGORY_META = {
  observability: { label: 'OBSERVABILITY', desc: 'Trace LLM calls, track spend, monitor AI performance' },
  evaluation: { label: 'EVALUATION', desc: 'Test prompts, measure output quality, validate responses' },
  context: { label: 'CONTEXT COMPRESSION', desc: 'Reduce tokens before LLM calls to lower cost and latency' },
  'model-gateway': { label: 'MODEL ROUTING', desc: 'Route between models, unify API calls, track spend' },
}
const DEFAULT_GOALS = ['evaluation', 'track costs', 'compress context', 'model routing']

function catMeta(key) {
  return CATEGORY_META[key] || { label: key.toUpperCase().replace(/-/g, ' '), desc: '' }
}

export default function Wizard() {
  const { settings, run, meta, connection } = useWorkbench()
  const [stage, setStage] = useState('idle')
  const [groups, setGroups] = useState({})
  const [hasPromptfoo, setHasPromptfoo] = useState(false)
  const [selections, setSelections] = useState({})
  const [rounds, setRounds] = useState([])
  const [installResults, setInstallResults] = useState([])
  const [scanError, setScanError] = useState('')
  const installing = useRef(false)

  const projectOk = !!settings.project_root

  async function startWizard() {
    setScanError('')
    const result = await run('Scanning for recommendations', async () => {
      const resp = await axios.post('/api/recommend', {
        project_root: settings.project_root,
        goals: DEFAULT_GOALS,
        assistant: settings.assistant || null,
        model_preference: settings.model_preference || 'local',
        scan_source: settings.scan_source,
      }, { headers: { 'X-StackWinnow-Token': meta?.action_token || '' } })
      return resp.data
    })
    if (!result) { setScanError('Scan failed — check the project path and backend.'); return }

    const libraryIds = new Set(
      (meta?.modes || []).filter(m => m.mode === 'library').map(m => m.tool_id)
    )
    setHasPromptfoo(result.recommendations.some(r => r.tool_id === 'promptfoo'))

    const grouped = {}
    for (const rec of result.recommendations) {
      if (!libraryIds.has(rec.tool_id)) continue
      grouped[rec.category] = [...(grouped[rec.category] || []), rec]
    }
    const ordered = {}
    for (const cat of CATEGORY_ORDER) { if (grouped[cat]) ordered[cat] = grouped[cat] }
    for (const [cat, tools] of Object.entries(grouped).sort()) { if (!ordered[cat]) ordered[cat] = tools }

    setGroups(ordered)
    const initSel = {}
    for (const cat of Object.keys(ordered)) initSel[cat] = new Set()
    setSelections(initSel)
    setStage('selecting')
  }

  function toggle(cat, toolId) {
    if (installing.current) return
    setSelections(prev => {
      const s = new Set(prev[cat])
      s.has(toolId) ? s.delete(toolId) : s.add(toolId)
      return { ...prev, [cat]: s }
    })
  }

  function setCat(cat, all) {
    if (installing.current) return
    setSelections(prev => ({
      ...prev,
      [cat]: all ? new Set(groups[cat].map(r => r.tool_id)) : new Set(),
    }))
  }

  function getSelected() {
    const out = []
    for (const cat of Object.keys(groups)) {
      for (const rec of groups[cat]) {
        if (selections[cat]?.has(rec.tool_id)) out.push({ ...rec, cat })
      }
    }
    return out
  }

  async function install() {
    if (installing.current) return
    const sel = getSelected()
    if (!sel.length) return
    installing.current = true

    const batches = []
    for (let i = 0; i < sel.length; i += 4) batches.push(sel.slice(i, i + 4))

    const liveRounds = batches.map(b => ({ tools: b, status: 'pending', outcomes: [], error: '' }))
    setRounds([...liveRounds])
    setStage('installing')

    const allResults = []

    for (let i = 0; i < batches.length; i++) {
      liveRounds[i] = { ...liveRounds[i], status: 'running' }
      setRounds([...liveRounds])

      try {
        const planResp = await axios.post('/api/workflow/plan', {
          project_root: settings.project_root,
          tool_ids: batches[i].map(t => t.tool_id),
          goals: DEFAULT_GOALS,
          model_preference: settings.model_preference || 'local',
        }, { headers: { 'X-StackWinnow-Token': meta?.action_token || '' } })

        const applyResp = await axios.post('/api/workflow/apply', {
          plan_id: planResp.data.plan_id,
          confirm: true,
        }, { headers: { 'X-StackWinnow-Token': meta?.action_token || '' } })

        const outcomes = applyResp.data.outcomes || []
        liveRounds[i] = { ...liveRounds[i], status: 'done', outcomes }
        setRounds([...liveRounds])

        for (const rec of batches[i]) {
          const o = outcomes.find(o => o.phase === rec.tool_id)
          allResults.push({ ...rec, outcome: o?.status || 'failed', message: o?.message || '' })
        }
      } catch (err) {
        const msg = err.response?.data?.detail || err.message || 'Failed'
        liveRounds[i] = { ...liveRounds[i], status: 'error', error: msg }
        setRounds([...liveRounds])
        for (const rec of batches[i]) {
          allResults.push({ ...rec, outcome: 'failed', message: msg })
        }
      }
    }

    setInstallResults(allResults)
    installing.current = false
    setStage('done')
  }

  function reset() {
    installing.current = false
    setStage('idle')
    setGroups({})
    setSelections({})
    setRounds([])
    setInstallResults([])
    setScanError('')
  }

  const selCount = getSelected().length

  return <>
    <Heading eyebrow="SELECT / INSTALL / VERIFY" title="Install tools in one guided flow." description="Scan your project, choose tools by category, then install them in one shot." />
    {!projectOk ? <NeedsProject /> : <>

      {stage === 'idle' && (
        <div className="panel wizard-start">
          <SectionTitle title="Guided installation" />
          <p className="small muted">Goals: <strong>{DEFAULT_GOALS.join(', ')}</strong></p>
          {scanError && <Notice tone="amber">{scanError}</Notice>}
          <div className="action-row">
            <button className="button primary" disabled={connection !== 'ready'} onClick={startWizard}>
              Start wizard
            </button>
          </div>
        </div>
      )}

      {stage === 'selecting' && (
        Object.keys(groups).length === 0
          ? <Notice>No library-mode tools matched these goals. Try wider goals in Scan options.</Notice>
          : <>
            <div className="wizard-info-bar">
              <span>{Object.values(groups).reduce((n, t) => n + t.length, 0)} tools · {Object.keys(groups).length} categories</span>
              {hasPromptfoo && <span className="muted">promptfoo available separately — use <code>stackwinnow promptfoo</code></span>}
            </div>
            {Object.entries(groups).map(([cat, tools]) => {
              const { label, desc } = catMeta(cat)
              const catSel = selections[cat] || new Set()
              return (
                <div key={cat} className="panel wizard-category">
                  <div className="wizard-cat-head">
                    <div>
                      <div className="eyebrow wizard-cat-label">{label}</div>
                      <p className="small muted" style={{ marginBottom: 0, marginTop: 4 }}>{desc}</p>
                    </div>
                    <div className="wizard-cat-controls">
                      <button className="text-button" onClick={() => setCat(cat, true)}>All</button>
                      <button className="text-button" onClick={() => setCat(cat, false)}>Skip</button>
                    </div>
                  </div>
                  <div className="wizard-tool-list">
                    {tools.map(rec => (
                      <label key={rec.tool_id} className={'wizard-tool-row' + (catSel.has(rec.tool_id) ? ' chosen' : '')}>
                        <input type="checkbox" checked={catSel.has(rec.tool_id)} onChange={() => toggle(cat, rec.tool_id)} />
                        <div className="wizard-tool-info">
                          <strong>{rec.name}</strong>
                          <span className="small muted">{rec.description}</span>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              )
            })}
            <div className="panel wizard-proceed">
              <span className="small">{selCount} tool{selCount !== 1 ? 's' : ''} selected</span>
              <div className="action-row" style={{ marginBottom: 0 }}>
                <button className="button secondary" onClick={reset}>Start over</button>
                <button className="button primary" disabled={selCount === 0} onClick={install}>
                  Proceed with installation
                </button>
              </div>
            </div>
          </>
      )}

      {stage === 'installing' && (
        <>
          <div className="panel">
            <SectionTitle title={`Installing — ${rounds.filter(r => r.status === 'done' || r.status === 'error').length} of ${rounds.length} rounds complete`} />
          </div>
          {rounds.map((round, i) => {
            const tone = round.status === 'done' ? 'green' : round.status === 'error' ? 'amber' : round.status === 'running' ? 'teal' : 'neutral'
            const label = { running: 'Installing…', done: 'Complete', error: 'Failed to plan', pending: 'Pending' }[round.status]
            return (
              <div key={i} className="panel wizard-round">
                <div className="wizard-round-head">
                  <strong>Round {i + 1} of {rounds.length}</strong>
                  <Badge tone={tone}>{label}</Badge>
                </div>
                <div className="wizard-install-list">
                  {round.tools.map(rec => {
                    const o = round.outcomes.find(o => o.phase === rec.tool_id)
                    const iconClass = o?.status === 'succeeded' ? 'ok'
                      : (round.status === 'error' || (round.status === 'done' && o)) ? 'fail'
                      : round.status === 'running' ? 'spin' : 'pending'
                    return (
                      <div key={rec.tool_id} className="wizard-install-row">
                        <span className={'wizard-icon wizard-icon-' + iconClass}>
                          {iconClass === 'ok' ? '✓' : iconClass === 'fail' ? '✗' : iconClass === 'pending' ? '○' : ''}
                        </span>
                        <strong>{rec.name}</strong>
                        {o && o.status !== 'succeeded' && (
                          <span className="small muted">{o.message?.split('\n')[0]?.slice(0, 80)}</span>
                        )}
                      </div>
                    )
                  })}
                </div>
                {round.error && (
                  <p className="diagnostic" style={{ marginTop: 10 }}>
                    <Badge tone="amber">error</Badge>{round.error}
                  </p>
                )}
              </div>
            )
          })}
        </>
      )}

      {stage === 'done' && (
        <div className="panel">
          <SectionTitle title="Results" />
          <div className="wizard-results">
            {installResults.map(r => (
              <div key={r.tool_id} className={'wizard-result-row wizard-result-' + (r.outcome === 'succeeded' ? 'ok' : 'fail')}>
                <span className={'wizard-icon wizard-icon-' + (r.outcome === 'succeeded' ? 'ok' : 'fail')}>
                  {r.outcome === 'succeeded' ? '✓' : '✗'}
                </span>
                <strong>{r.name}</strong>
                <Badge tone={r.outcome === 'succeeded' ? 'green' : 'amber'}>
                  {r.outcome === 'succeeded' ? 'installed' : 'failed'}
                </Badge>
                {r.outcome !== 'succeeded' && r.message && (
                  <span className="small muted">{r.message.split('\n')[0]?.slice(0, 80)}</span>
                )}
              </div>
            ))}
          </div>
          <p className="small muted" style={{ marginTop: 16 }}>
            {installResults.filter(r => r.outcome === 'succeeded').length} of {installResults.length} tools installed.{' '}
            {installResults.every(r => r.outcome === 'succeeded') ? 'All done.' : 'Review errors above.'}
          </p>
          <div className="action-row" style={{ marginBottom: 0 }}>
            <button className="button secondary" onClick={reset}>Run again</button>
          </div>
        </div>
      )}

    </>}
  </>
}
