import { useState, useEffect } from 'react'
import axios from 'axios'

const ASSISTANTS = ['none', 'claude', 'openai', 'gemini', 'copilot']

export default function Recommend() {
  const [path, setPath] = useState(() => localStorage.getItem('recommend_path') || '')
  const [goals, setGoals] = useState(() => JSON.parse(localStorage.getItem('recommend_goals') || '[]'))
  const [goalInput, setGoalInput] = useState('')
  const [assistant, setAssistant] = useState(() => localStorage.getItem('recommend_assistant') || 'none')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { localStorage.setItem('recommend_path', path) }, [path])
  useEffect(() => { localStorage.setItem('recommend_goals', JSON.stringify(goals)) }, [goals])
  useEffect(() => { localStorage.setItem('recommend_assistant', assistant) }, [assistant])

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
    const pending = goalInput.split(',').map(s => s.trim()).filter(Boolean)
    const finalGoals = [...goals]
    pending.forEach(g => { if (!finalGoals.includes(g)) finalGoals.push(g) })
    if (pending.length) { setGoals(finalGoals); setGoalInput('') }

    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await axios.post('/api/recommend', {
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
      <h1 className="text-2xl font-bold mb-1">Recommend Tools</h1>
      <p className="text-gray-500 text-sm mb-6">
        Get personalized tool recommendations based on your project profile.
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
          {loading ? 'Analysing…' : 'Get Recommendations'}
        </button>
      </form>

      {error && (
        <div className="mt-4 bg-red-50 border border-red-200 text-red-700 rounded p-4 text-sm">{error}</div>
      )}

      {result && <RecommendResult data={result} />}
    </div>
  )
}

function RecommendResult({ data }) {
  const recs = data.recommendations ?? []
  const newTools = recs.filter(r => !r.already_declared)
  const existing = recs.filter(r => r.already_declared)

  return (
    <div className="mt-6 space-y-4">

      {/* Already installed — just a compact notice */}
      {existing.length > 0 && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm">
          <span className="font-medium text-green-800">Already in your project: </span>
          <span className="text-green-700">{existing.map(r => r.tool_id).join(', ')}</span>
        </div>
      )}

      <p className="text-sm text-gray-500">
        {newTools.length} new tool{newTools.length !== 1 ? 's' : ''} recommended
      </p>

      {newTools.map((rec, i) => (
        <div key={i} className="bg-white rounded-lg border-l-4 border-indigo-500 border p-4 shadow-sm">
          <div className="flex justify-between items-start mb-1">
            <span className="font-semibold text-gray-800">{rec.name ?? rec.tool_id}</span>
            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-mono">{rec.tool_id}</span>
          </div>

          {rec.description && <p className="text-sm text-gray-500 mb-3">{rec.description}</p>}

          {rec.reasons?.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Why add this</p>
              <ul className="text-sm text-gray-700 space-y-1">
                {rec.reasons.map((r, j) => <li key={j} className="flex gap-2"><span className="text-indigo-400">→</span>{r.message ?? r}</li>)}
              </ul>
            </div>
          )}

          {rec.eligibility?.reasons?.length > 0 && (
            <div className="mb-3">
              <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Requirements</p>
              <ul className="text-sm text-gray-600 space-y-0.5 list-disc ml-4">
                {rec.eligibility.reasons.map((r, j) => <li key={j}>{r.message ?? r}</li>)}
              </ul>
            </div>
          )}

          {rec.alternatives?.length > 0 && (
            <p className="text-xs text-gray-400 mt-2">Alternatives: {rec.alternatives.join(', ')}</p>
          )}
        </div>
      ))}

      {newTools.length === 0 && (
        <p className="text-gray-400 text-sm">No new tools to recommend — your project already covers these goals.</p>
      )}
    </div>
  )
}
