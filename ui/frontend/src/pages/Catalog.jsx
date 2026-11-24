import { useEffect, useState } from 'react'
import axios from 'axios'

const CATEGORIES = [
  'context', 'caching', 'model-gateway', 'evaluation',
  'browser-automation', 'observability', 'coding', 'orchestration', 'prompt-optimization',
]

const BADGE = {
  adapter_available: 'bg-green-100 text-green-800',
  catalog_only: 'bg-gray-100 text-gray-600',
}

export default function Catalog() {
  const [tools, setTools] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    setLoading(true)
    const params = {}
    if (category) params.category = category
    if (q) params.q = q
    axios.get('/api/catalog', { params })
      .then(r => { setTools(r.data.tools); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [category, q])

  return (
    <div>
      <h1 className="text-2xl font-bold mb-1">Tool Catalog</h1>
      <p className="text-gray-500 text-sm mb-6">
        {tools.length} tools · click a row for details
      </p>

      {/* Filters */}
      <div className="flex gap-3 mb-5 flex-wrap">
        <input
          className="border rounded px-3 py-1.5 text-sm w-56"
          placeholder="Search…"
          value={q}
          onChange={e => setQ(e.target.value)}
        />
        <select
          className="border rounded px-3 py-1.5 text-sm"
          value={category}
          onChange={e => setCategory(e.target.value)}
        >
          <option value="">All categories</option>
          {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {error && <p className="text-red-600">{error}</p>}
      {loading && <p className="text-gray-400">Loading…</p>}

      {/* Table */}
      {!loading && (
        <div className="overflow-x-auto rounded-lg border bg-white shadow-sm">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 text-gray-500 uppercase text-xs">
              <tr>
                {['ID', 'Category', 'Status', 'Description'].map(h => (
                  <th key={h} className="px-4 py-3 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {tools.map(t => (
                <tr
                  key={t.tool_id}
                  className="hover:bg-indigo-50 cursor-pointer transition-colors"
                  onClick={() => setSelected(selected?.tool_id === t.tool_id ? null : t)}
                >
                  <td className="px-4 py-3 font-mono font-medium text-indigo-700">{t.tool_id}</td>
                  <td className="px-4 py-3 text-gray-600">{t.category}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${BADGE[t.availability] ?? 'bg-gray-100 text-gray-600'}`}>
                      {t.availability}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-700 max-w-sm truncate">{t.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail panel */}
      {selected && <ToolDetail tool={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}

function ToolDetail({ tool, onClose }) {
  const [detail, setDetail] = useState(null)

  useEffect(() => {
    axios.get(`/api/catalog/${tool.tool_id}`)
      .then(r => setDetail(r.data))
  }, [tool.tool_id])

  return (
    <div className="fixed inset-0 bg-black/40 flex justify-end z-10" onClick={onClose}>
      <div
        className="w-full max-w-lg bg-white shadow-xl overflow-y-auto p-6"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-start mb-4">
          <div>
            <h2 className="text-xl font-bold">{detail?.name ?? tool.name}</h2>
            <p className="text-gray-500 text-sm">{tool.tool_id}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none">&times;</button>
        </div>

        {!detail && <p className="text-gray-400">Loading…</p>}
        {detail && (
          <div className="space-y-4 text-sm">
            <p>{detail.description}</p>

            {detail.license_scope && (
              <Section title="License">{detail.license_scope}</Section>
            )}
            {detail.prerequisites?.length > 0 && (
              <Section title="Prerequisites">
                <ul className="list-disc ml-4 space-y-1">
                  {detail.prerequisites.map((p, i) => <li key={i}>{p}</li>)}
                </ul>
              </Section>
            )}
            {detail.limitations?.length > 0 && (
              <Section title="Limitations">
                <ul className="list-disc ml-4 space-y-1">
                  {detail.limitations.map((l, i) => <li key={i}>{l}</li>)}
                </ul>
              </Section>
            )}
            {detail.alternatives?.length > 0 && (
              <Section title="Alternatives">
                <span className="text-gray-600">{detail.alternatives.join(', ')}</span>
              </Section>
            )}
            {detail.repository && (
              <Section title="Repository">
                <a href={detail.repository} target="_blank" rel="noreferrer"
                   className="text-indigo-600 underline break-all">{detail.repository}</a>
              </Section>
            )}

            <Section title="Eligibility">
              {detail.eligibility?.reasons?.map((r, i) => (
                <p key={i} className="text-gray-500">{r.message}</p>
              ))}
            </Section>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div>
      <h3 className="font-semibold text-gray-700 mb-1">{title}</h3>
      <div className="text-gray-600">{children}</div>
    </div>
  )
}
