export default function SourceFindings({ discovery }) {
  if (!discovery || discovery.status === 'not-scanned') return null
  return (
    <section className="bg-white rounded-lg border p-4 shadow-sm space-y-3">
      <h2 className="font-semibold text-gray-700">Source discovery</h2>
      <p className="text-sm text-gray-500">
        Coverage: {discovery.status} · {discovery.files_scanned} files scanned
      </p>
      {discovery.findings.map((finding, i) => (
        <div key={i} className="border-t pt-3 text-sm space-y-1">
          <p className="font-medium">{finding.summary}</p>
          <p className="text-xs text-gray-500">Confidence in pattern: {finding.confidence}</p>
          {finding.evidence.map((e, j) => (
            <p key={j} className="font-mono text-xs break-all">{e.path}:{e.line}</p>
          ))}
          <p className="text-indigo-700">{finding.question}</p>
          {finding.caveats.map((c, j) => <p key={j} className="text-gray-500 text-xs">{c}</p>)}
        </div>
      ))}
      {discovery.findings.length === 0 && (
        <p className="text-sm text-gray-500">No supported source patterns found. Other opportunities may exist.</p>
      )}
      {[...discovery.diagnostics, ...discovery.limitations].map((d, i) => (
        <p key={i} className="text-xs text-gray-500">{d}</p>
      ))}
    </section>
  )
}
