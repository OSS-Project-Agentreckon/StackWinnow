import { createContext, useContext, useEffect, useRef, useState } from 'react'
import axios from 'axios'

// Keep the shared context identity stable during Vite hot updates.
const Context = import.meta.hot?.data.context || createContext(null)
if (import.meta.hot) import.meta.hot.data.context = Context
export const useWorkbench = () => useContext(Context)
export function errorText(error) {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : error.message || 'The request could not be completed.'
}
export function download(name, content, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([typeof content === 'string' ? content : JSON.stringify(content, null, 2)], { type }))
  const link = document.createElement('a')
  link.href = url; link.download = name; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function savedSettings() {
  const defaults = { project_root: '', goals: '', assistant: '', platform: '', model_preference: 'any', config_path: '', scan_source: true }
  try {
    const raw = JSON.parse(localStorage.getItem('stackwinnow.workspace') || 'null')
    if (raw && typeof raw === 'object') {
      for (const key of Object.keys(defaults)) if (typeof raw[key] === typeof defaults[key]) defaults[key] = raw[key]
    } else {
      defaults.project_root = localStorage.getItem('recommend_path') || localStorage.getItem('inspect_path') || ''
    }
  } catch { /* Invalid saved preferences do not prevent opening the workspace. */ }
  return defaults
}
export function requestFor(settings, selected = []) {
  return { ...settings, goals: settings.goals.split(',').map(s => s.trim()).filter(Boolean), assistant: settings.assistant || null,
    platform: settings.platform || null, model_preference: settings.model_preference || null,
    config_path: settings.config_path || null, selected_tools: selected }
}
export function WorkbenchProvider({ children }) {
  const [settings, setSettings] = useState(savedSettings)
  const [meta, setMeta] = useState(null)
  const [connection, setConnection] = useState('connecting')
  const [catalog, setCatalog] = useState([])
  const [catalogTarget, setCatalogTarget] = useState('')
  const compatibilityReady = catalogTarget === JSON.stringify([settings.assistant, settings.platform])
  const [scan, setScan] = useState(null)
  const [selected, setSelected] = useState([])
  const [plan, setPlan] = useState(null)
  const [operation, setOperation] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const sequence = useRef(0)
  const busyRef = useRef(false)
  useEffect(() => { localStorage.setItem('stackwinnow.workspace', JSON.stringify(settings)) }, [settings])
  useEffect(() => {
    let active = true
    axios.get('/api/meta').then(({ data }) => {
      if (!active) return
      if (data.api_revision !== 2) { setConnection('outdated'); return }
      setMeta(data); setConnection('ready')
    }).catch(() => { if (active) setConnection('offline') })
    return () => { active = false }
  }, [])
  useEffect(() => {
    if (!meta) return
    const controller = new AbortController()
    axios.get('/api/catalog', {params: {assistant: settings.assistant || undefined, platform: settings.platform || undefined}, signal: controller.signal})
      .then(({ data }) => { setCatalog(data.tools); setCatalogTarget(JSON.stringify([settings.assistant, settings.platform])) })
      .catch(err => { if (!axios.isCancel(err)) setError(errorText(err)) })
    return () => controller.abort()
  }, [meta, settings.assistant, settings.platform])
  function update(key, value) {
    if (busyRef.current) return
    setSettings(previous => ({ ...previous, [key]: value }))
    setPlan(null); setOperation(null)
    if (key === 'project_root') { sequence.current++; setScan(null) }
  }
  function toggleTool(id) {
    if (busyRef.current) return
    setSelected(previous => previous.includes(id) ? previous.filter(x => x !== id) : [...previous, id])
    setPlan(null); setOperation(null)
  }
  function adoptProfilePlan(value) {
    setSelected(value.document.request.selections.map(s => s.tool_id))
    setSettings(previous => ({ ...previous, assistant: value.document.request.assistant,
      model_preference: value.document.request.model_preference,
      goals: value.document.request.goals.join(', ') }))
    setPlan(value); setOperation(null)
  }
  async function post(endpoint, body) {
    return (await axios.post('/api/' + endpoint, body, {headers: {'X-StackWinnow-Token': meta?.action_token || ''}})).data
  }
  async function run(label, task) {
    if (busyRef.current) return
    busyRef.current = true; setBusy(label); setError('')
    try { return await task() } catch (err) { setError(errorText(err)); return null }
    finally { busyRef.current = false; setBusy('') }
  }
  async function scanProject() {
    if (busyRef.current) return
    const body = requestFor(settings)
    const id = ++sequence.current
    await run('Scanning project source', async () => {
      const result = await post('recommend', body)
      if (id === sequence.current) setScan({result, request: body, at: new Date().toLocaleTimeString()})
    })
  }
  return <Context.Provider value={{settings, update, meta, connection, catalog, compatibilityReady, scan, selected, toggleTool,
    plan, setPlan, adoptProfilePlan, operation, setOperation, busy, error, setError, run, post, scanProject}}>{children}</Context.Provider>
}
