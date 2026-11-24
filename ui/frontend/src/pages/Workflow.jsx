import { useEffect, useState } from 'react'
import axios from 'axios'

const STEPS = ['Select mode', 'Configure', 'View plan']

const TOOL_PLAN_KEYS = ['headroom', 'promptfoo', 'playwright', 'graphify']

function PlanView({ plan, onBack }) {
  const tools = TOOL_PLAN_KEYS.filter(k => plan[k] != null)
  const projectRoot = plan.project_root ?? ''
  const toolList = plan.request?.selections?.map(s => s.tool_id).join(' ') ?? tools.join(' ')

  // Flatten all installation steps across tools in order
  const allSteps = tools.flatMap(k => {
    const inst = plan[k]?.installation
    return (inst?.steps ?? []).map(s => ({ ...s, _tool: k }))
  })
  // Add a final verify step
  const displaySteps = [...allSteps, { step_id: '__verify', _tool: 'verify', description: 'Verify installation and record result.' }]

  // Files that will be written
  const configFiles = tools
    .map(k => plan[k]?.configuration?.relative_path)
    .filter(Boolean)

  const applyCmd = `stackwinnow workflow apply plan.json`
  const planCmd = `stackwinnow workflow plan ${projectRoot}${tools.map(t => ` --tool ${t}`).join('')} --json > plan.json`

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Workflow plan</h2>
        <button onClick={onBack} className="text-xs text-indigo-500 hover:underline">back</button>
      </div>

      {/* Summary row */}
      <div className="bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-3 text-sm flex flex-wrap gap-4">
        <span><span className="text-gray-500">Tools:</span> <span className="font-medium capitalize">{tools.join(', ')}</span></span>
        <span><span className="text-gray-500">Phases:</span> <span className="font-mono text-xs">{tools.join(' → ')} → verify</span></span>
      </div>

      {/* Steps */}
      <div>
        <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Installation steps</p>
        <div className="space-y-2">
          {displaySteps.map((s, i) => (
            <div key={s.step_id} className="flex gap-3 items-start bg-white border rounded-lg p-3 shadow-sm">
              <span className={`flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold text-white
                ${s._tool === 'verify' ? 'bg-green-500' : 'bg-indigo-600'}`}>{i + 1}</span>
              <div>
                <p className="text-sm text-gray-800">{s.description}</p>
                {s._tool !== 'verify' && (
                  <span className="text-xs text-gray-400 font-mono capitalize">{s._tool}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Config files */}
      {configFiles.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase mb-2">Files that will be created</p>
          <div className="space-y-1">
            {configFiles.map(f => (
              <div key={f} className="flex items-center gap-2 bg-white border rounded px-3 py-2 text-sm">
                <span className="text-green-500 font-bold">+</span>
                <code className="font-mono text-xs text-gray-700">{f}</code>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Apply instructions */}
      <div className="bg-gray-50 border rounded-lg p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-700">To apply this plan to your repo:</p>
        <div>
          <p className="text-xs text-gray-500 mb-1">1. Save the plan to a file:</p>
          <pre className="bg-white border rounded px-3 py-2 text-xs font-mono overflow-x-auto text-gray-800">{planCmd}</pre>
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1">2. Apply it:</p>
          <pre className="bg-white border rounded px-3 py-2 text-xs font-mono overflow-x-auto text-gray-800">{applyCmd}</pre>
        </div>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
        This is a dry-run preview. No changes have been made to your project.
      </div>
    </div>
  )
}

export default function Workflow() {
  const [step, setStep] = useState(0)
  const [modes, setModes] = useState([])
  const [filteredModes, setFilteredModes] = useState([])
  const [modesLoading, setModesLoading] = useState(true)
  const [selectedMode, setSelectedMode] = useState(null)

  // inherit stored path/goals from Inspect/Recommend
  const [path, setPath] = useState(() => localStorage.getItem('recommend_path') || localStorage.getItem('inspect_path') || '')
  const [goals, setGoals] = useState(() => JSON.parse(localStorage.getItem('recommend_goals') || localStorage.getItem('inspect_goals') || '[]'))
  const [goalInput, setGoalInput] = useState('')
  const [toolIds, setToolIds] = useState([])
  const [toolInput, setToolInput] = useState('')

  const [plan, setPlan] = useState(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    axios.get('/api/workflow/modes')
      .then(r => {
        const allModes = Array.isArray(r.data) ? r.data : (r.data.modes ?? [])
        setModes(allModes)

        // cross-check with recommendations if we have a project path
        const storedPath = localStorage.getItem('recommend_path') || localStorage.getItem('inspect_path')
        const storedGoals = JSON.parse(localStorage.getItem('recommend_goals') || localStorage.getItem('inspect_goals') || '[]')
        if (storedPath) {
          axios.post('/api/recommend', { project_root: storedPath, goals: storedGoals })
            .then(rec => {
              const recommended = new Set(
                (rec.data.recommendations ?? [])
                  .filter(r => !r.already_declared)
                  .map(r => r.tool_id)
              )
              const relevant = allModes.filter(m => recommended.has(m.tool_id))
              setFilteredModes(relevant.length > 0 ? relevant : allModes)
            })
            .catch(() => setFilteredModes(allModes))
        } else {
          setFilteredModes(allModes)
        }
        setModesLoading(false)
      })
      .catch(() => setModesLoading(false))
  }, [])

  function addGoal() {
    const g = goalInput.trim()
    if (g && !goals.includes(g)) setGoals([...goals, g])
    setGoalInput('')
  }

  function addTool() {
    const t = toolInput.trim()
    if (t && !toolIds.includes(t)) setToolIds([...toolIds, t])
    setToolInput('')
  }

  async function fetchPlan() {
    setPlanLoading(true)
    setError(null)
    setPlan(null)
    try {
      const r = await axios.post('/api/workflow/plan', {
        project_root: path,
        goals,
        tool_ids: toolIds,
      })
      setPlan(r.data)
      setStep(2)
    } catch (err) {
      setError(err.response?.data?.detail ?? err.message)
    } finally {
      setPlanLoading(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-1">Workflow</h1>
      <p className="text-gray-500 text-sm mb-6">
        Plan an AI-tooling adoption workflow for your project.
      </p>

      {/* Stepper */}
      <div className="flex items-center gap-2 mb-8">
        {STEPS.map((label, i) => (
          <div key={i} className="flex items-center gap-2">
            <button
              onClick={() => i < step ? setStep(i) : undefined}
              className={`w-7 h-7 rounded-full text-xs font-bold flex items-center justify-center transition-colors
                ${step === i ? 'bg-indigo-600 text-white' : i < step ? 'bg-indigo-200 text-indigo-700 cursor-pointer hover:bg-indigo-300' : 'bg-gray-200 text-gray-400'}`}
            >
              {i + 1}
            </button>
            <span className={`text-sm ${step === i ? 'font-medium' : 'text-gray-400'}`}>{label}</span>
            {i < STEPS.length - 1 && <span className="text-gray-200 mx-1">›</span>}
          </div>
        ))}
      </div>

      {/* Step 0: Select mode */}
      {step === 0 && (
        <div>
          <h2 className="font-semibold mb-1">Choose a workflow mode</h2>
          {filteredModes.length < modes.length && (
            <p className="text-xs text-indigo-500 mb-3">
              Showing {filteredModes.length} mode{filteredModes.length !== 1 ? 's' : ''} recommended for your project · <button className="underline" onClick={() => setFilteredModes(modes)}>show all {modes.length}</button>
            </p>
          )}
          {modesLoading && <p className="text-gray-400 text-sm">Loading modes…</p>}
          {!modesLoading && filteredModes.length === 0 && (
            <p className="text-gray-400 text-sm">No modes available from backend.</p>
          )}
          <div className="space-y-3">
            {filteredModes.map(m => (
              <button
                key={m.tool_id}
                onClick={() => { setSelectedMode(m); setToolIds([m.tool_id]); setStep(1) }}
                className="w-full text-left bg-white border rounded-lg p-4 shadow-sm hover:border-indigo-400 hover:shadow transition-all"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold text-gray-800 capitalize">{m.tool_id}</span>
                  <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">{m.mode}</span>
                  <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full ml-auto">v{m.version}</span>
                </div>
                {m.description && <p className="text-sm text-gray-500">{m.description}</p>}
                {m.requirements?.length > 0 && (
                  <p className="text-xs text-gray-400 mt-2 font-mono">{m.requirements.join(' · ')}</p>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Step 1: Configure */}
      {step === 1 && (
        <div className="bg-white rounded-lg border p-5 shadow-sm space-y-5">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm text-gray-500">Mode:</span>
            <span className="font-semibold text-sm capitalize">{selectedMode?.tool_id}</span>
            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">{selectedMode?.mode}</span>
            <button onClick={() => setStep(0)} className="ml-auto text-xs text-indigo-500 hover:underline">change</button>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Project path</label>
            <input
              className="w-full border rounded px-3 py-2 text-sm"
              placeholder="/path/to/your/project"
              value={path}
              onChange={e => setPath(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Goals (optional)</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {goals.map(g => (
                <span key={g} className="bg-indigo-100 text-indigo-800 text-xs px-2 py-1 rounded-full flex items-center gap-1">
                  {g}
                  <button type="button" onClick={() => setGoals(goals.filter(x => x !== g))} className="text-indigo-400 hover:text-indigo-700">&times;</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                className="flex-1 border rounded px-3 py-1.5 text-sm"
                placeholder="Add goal"
                value={goalInput}
                onChange={e => setGoalInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addGoal())}
              />
              <button type="button" onClick={addGoal} className="px-3 py-1.5 bg-gray-100 rounded text-sm hover:bg-gray-200">Add</button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Tool IDs to include (optional)</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {toolIds.map(t => (
                <span key={t} className="bg-gray-100 text-gray-700 text-xs px-2 py-1 rounded-full font-mono flex items-center gap-1">
                  {t}
                  <button type="button" onClick={() => setToolIds(toolIds.filter(x => x !== t))} className="text-gray-400 hover:text-gray-700">&times;</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                className="flex-1 border rounded px-3 py-1.5 text-sm font-mono"
                placeholder="e.g. memory-bank"
                value={toolInput}
                onChange={e => setToolInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addTool())}
              />
              <button type="button" onClick={addTool} className="px-3 py-1.5 bg-gray-100 rounded text-sm hover:bg-gray-200">Add</button>
            </div>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 rounded p-3 text-sm">{error}</div>
          )}

          <button
            onClick={fetchPlan}
            disabled={planLoading || !path}
            className="w-full bg-indigo-600 text-white rounded py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {planLoading ? 'Planning…' : 'Generate Plan'}
          </button>
        </div>
      )}

      {/* Step 2: Plan */}
      {step === 2 && plan && (
        <PlanView plan={plan} onBack={() => setStep(1)} />
      )}
    </div>
  )
}
