import type { Citation, Inspection } from '../api/types'
import { formatDate } from '../lib/format'

// "Paper" renderings of source documents: they look like scans, so they
// stay white with dark ink in both themes.

export function InspectionPaper({ inspection, compact = false }: { inspection: Inspection; compact?: boolean }) {
  return (
    <div className={`rounded-md border border-neutral-300 bg-white text-neutral-900 shadow-sm ${compact ? 'p-3 text-[10px]' : 'p-4 text-xs'}`}>
      <div className="flex items-baseline justify-between border-b border-neutral-400 pb-1.5">
        <span className={`font-serif font-semibold ${compact ? 'text-xs' : 'text-sm'}`}>Inspection Report</span>
        <span className="text-neutral-500">
          {inspection.report_no} · Page {inspection.page} of {inspection.pages}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-[5.5rem_1fr] border border-neutral-300">
        {[
          ['Asset', inspection.tag],
          ['Date', formatDate(inspection.date)],
          ['Inspector', inspection.inspector],
        ].map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="border-b border-neutral-300 bg-neutral-100 px-2 py-1 font-medium">{k}</dt>
            <dd className="border-b border-neutral-300 px-2 py-1">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-2 font-medium">Findings</div>
      <table className="mt-1 w-full border border-neutral-300">
        <tbody>
          {inspection.findings.map((f) => (
            <tr key={f.item} className="border-b border-neutral-300 last:border-0">
              <td className="w-2/5 bg-neutral-100 px-2 py-1">{f.item}</td>
              <td className="px-2 py-1">
                <span className={f.flagged && f.item === 'Shaft alignment' ? 'bg-yellow-200 px-1 font-semibold' : ''}>{f.result}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!compact && (
        <div className="mt-3 flex items-end justify-between text-neutral-500">
          <span>Signed: {inspection.inspector}</span>
          <span className="font-serif italic">— handwritten notes on page 3 —</span>
        </div>
      )}
    </div>
  )
}

/** Excerpt of the cited source, with the quoted line highlighted. */
export function CitationSource({ citation, inspection }: { citation: Citation; inspection?: Inspection | null }) {
  if (citation.kind === 'inspection' && inspection) return <InspectionPaper inspection={inspection} compact />

  return (
    <div className="rounded-md border border-neutral-300 bg-white p-3 text-[11px] leading-relaxed text-neutral-900 shadow-sm">
      <div className="mb-1.5 border-b border-neutral-300 pb-1 font-serif text-xs font-semibold">
        {citation.kind === 'manual' ? 'Section 7.3 · Mechanical seals' : citation.title}
      </div>
      {citation.kind === 'manual' && (
        <p className="text-neutral-600">
          Mechanical seals rely on flat, evenly loaded faces. Check alignment after any coupling work.
        </p>
      )}
      <p className="mt-1">
        <mark className="bg-yellow-200 px-0.5 text-neutral-900">{citation.quote}</mark>
      </p>
      {citation.kind === 'manual' && (
        <p className="mt-1 text-neutral-600">Recommended tolerance: 0.05 mm (laser alignment).</p>
      )}
    </div>
  )
}
