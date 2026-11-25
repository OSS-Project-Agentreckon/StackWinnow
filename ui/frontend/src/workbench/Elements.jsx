import { useState } from 'react'
import { Link } from 'react-router-dom'

export function Icon({name = 'scan', size = 20}) {
  const paths = {
    scan: <><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><path d="m8 12 3 3 5-6"/></>,
    files: <><path d="M14 2H5v20h14V7z"/><path d="M14 2v6h5M8 12h8m-8 4h5"/></>,
    catalog: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    workflow: <><rect x="2" y="8" width="6" height="8" rx="2"/><rect x="16" y="8" width="6" height="8" rx="2"/><path d="M8 12h8m-4-4 4 4-4 4"/></>,
    profiles: <><path d="M12 3v12m-4-4 4 4 4-4M4 15v6h16v-6"/></>,
    reports: <><path d="M5 3h14v18H5zM8 7h8M8 11h8M8 15h5"/></>,
    environment: <><rect x="3" y="3" width="18" height="14" rx="2"/><path d="M7 21h10m-5-4v4M6 8l3 2-3 2m6 0h5"/></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
    check: <path d="m4 12 5 5L20 6"/>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.scan}</svg>
}
export function Badge({children, tone = 'neutral'}) { return <span className={'badge badge-' + tone}>{children}</span> }
export function Heading({eyebrow, title, description, children}) {
  return <header className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{children}</header>
}
export function Empty({title, children, action}) {
  return <div className="empty-state"><span className="empty-icon"><Icon size={26}/></span><h3>{title}</h3><p>{children}</p>{action}</div>
}
export function JsonDetails({value, label = 'Inspect full JSON'}) {
  return <details className="json-details"><summary>{label}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
}
export function CopyButton({text}) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }
  return <button className="copy-button" onClick={copy} title="Copy to clipboard">{copied ? 'Copied!' : 'Copy'}</button>
}
export function NeedsProject() { return <Empty title="Choose a project to begin">Enter a local project path in the workspace bar above.</Empty> }
export function SectionTitle({title, count, children}) { return <div className="section-title"><h2>{title} {count !== undefined && <span>{count}</span>}</h2>{children}</div> }
export function Notice({children, tone = 'info'}) { return <div className={'notice notice-' + tone}>{children}</div> }
export function ScanLink() { return <Link className="button secondary" to="/recommend">Go to discovery <Icon name="arrow" size={16}/></Link> }
