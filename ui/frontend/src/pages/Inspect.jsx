import { useState, useEffect } from 'react'
import axios from 'axios'

const ASSISTANTS = ['none', 'claude', 'openai', 'gemini', 'copilot']

export default function Inspect() {
  const [path, setPath] = useState(() => localStorage.getItem('inspect_path') || '')
  const [goals, setGoals] = useState(() => JSON.parse(localStorage.getItem('inspect_goals') || '[]'))
  const [goalInput, setGoalInput] = useState('')
  const [assistant, setAssistant] = useState(() => localStorage.getItem('inspect_assistant') || 'none')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { localStorage.setItem('inspect_path', path) }, [path])
  useEffect(() => { localStorage.setItem('inspect_goals', JSON.stringify(goals)) }, [goals])
  useEffect(() => { localStorage.setItem('inspect_assistant', assistant) }, [assistant])

  function addGoal(e) {
    if (e && e.preventDefault) e.preventDefault()
    const parts = goalInput.split(',').map(s => s.trim()).filter(Boolean)
    const newGoals = [...goals]
    parts.forEach(g => { if (!newGoals.includes(g)) newGoals.push(g) })
    setGoals(newGoals)
    setGoalInput('')
  }

  function removeGoal(g) {
    setGoals(goals.filter(x => x !== g))
  }

  async function submit(e) {
    e.preventDefault()
    // auto-add any unsaved goal text before submitting
    const pending = goalInput.split(',').map(s => s.trim()).filter(Boolean)
    const finalGoals = [...goals]
    pending.forEach(g => { if (!finalGoals.includes(g)) finalGoals.push(g) })
    if (pending.length) { setGoals(finalGoals); setGoalInput('') }

    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await axios.post('/api/inspect', {
        project_root: path,
        goals: finalGoals,
        assistant: assistant === 'none' ? null : assistant,
      })
      setResult(r.data)
    } catch (err) {
      setError(err.response?.data?.detail ?? err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-1">Inspect Project</h1>
      <p className="text-gray-500 text-sm mb-6">
        Detect what AI tooling is in use and profile your project.
      </p>

      <form onSubmit={submit} className="space-y-5 bg-white rounded-lg border p-5 shadow-sm">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Project path</label>
          <input
            required
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
                <button type="button" onClick={() => removeGoal(g)} className="text-indigo-400 hover:text-indigo-700">&times;</button>
              </span>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              className="flex-1 border rounded px-3 py-1.5 text-sm"
              placeholder="Add goal and press Enter"
              value={goalInput}
              onChange={e => setGoalInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addGoal(e)}
            />
            <button
              type="button"
              onClick={addGoal}
              className="px-3 py-1.5 bg-gray-100 rounded text-sm hover:bg-gray-200"
            >Add</button>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Primary assistant</label>
          <select
            className="border rounded px-3 py-2 text-sm"
            value={assistant}
            onChange={e => setAssistant(e.target.value)}
          >
            {ASSISTANTS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-indigo-600 text-white rounded py-2 text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? 'Inspecting…' : 'Inspect'}
        </button>
      </form>

      {error && (
        <div className="mt-4 bg-red-50 border border-red-200 text-red-700 rounded p-4 text-sm">{error}</div>
      )}

      {result && <InspectResult data={result} />}
    </div>
  )
}

function InspectResult({ data }) {
  const profile = data.profile ?? {}
  const goals = profile.goals ?? []
  const facts = profile.facts ?? {}
  const evidence = profile.evidence ?? []

  const simpleFields = {
    'Project Root': profile.project_root,
    'Assistant': profile.assistant,
    'Operating System': profile.operating_system,
    'Model Preference': data.model_preference,
  }

  return (
    <div className="mt-6 space-y-5">
      <Section title="Profile">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {Object.entries(simpleFields).map(([label, val]) =>
            val ? (
              <div key={label}>
                <dt className="text-gray-500">{label}</dt>
                <dd className="font-medium">{val}</dd>
              </div>
            ) : null
          )}
        </dl>
        {goals.length > 0 && (
          <div className="mt-3">
            <p className="text-xs text-gray-500 mb-1">Goals</p>
            <div className="flex flex-wrap gap-2">
              {goals.map((g, i) => (
                <span key={i} className="bg-indigo-100 text-indigo-800 text-xs px-2 py-1 rounded-full">{g}</span>
              ))}
            </div>
          </div>
        )}
      </Section>

      {Object.keys(facts).length > 0 && (
        <Section title="Detected facts">
          <dl className="space-y-2 text-sm">
            {Object.entries(facts).map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <span className="text-green-500 font-bold flex-shrink-0">✓</span>
                <div>
                  <span className="font-medium capitalize">{k.replace(/_/g, ' ')}: </span>
                  <span className="text-gray-600">{Array.isArray(v) ? v.join(', ') : String(v)}</span>
                </div>
              </div>
            ))}
          </dl>
        </Section>
      )}

      {evidence.length > 0 && (
        <Section title="Evidence">
          <ul className="space-y-1 text-xs font-mono text-gray-600">
            {evidence.map((e, i) => <li key={i}>{typeof e === 'string' ? e : (e.path ?? JSON.stringify(e))}</li>)}
          </ul>
        </Section>
      )}

      {data.diagnostics?.length > 0 && (
        <Section title="Diagnostics">
          <ul className="space-y-1 text-sm">
            {data.diagnostics.map((d, i) => (
              <li key={i} className="flex gap-2">
                <span className={
                  d.status === 'ok' ? 'text-green-500' :
                  d.status === 'skipped' ? 'text-gray-300' : 'text-amber-500'
                }>●</span>
                <span className={d.status === 'skipped' ? 'text-gray-400' : 'text-gray-700'}>
                  {d.message}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="bg-white rounded-lg border p-4 shadow-sm">
      <h2 className="font-semibold text-gray-700 mb-3">{title}</h2>
      {children}
    </div>
  )
}
