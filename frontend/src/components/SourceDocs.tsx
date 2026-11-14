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
          {inspection.report_no || inspection.id} · Page {inspection.page} of {inspection.pages}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-[5.5rem_1fr] border border-neutral-300">
        {[
          ['Asset', inspection.tag],
          ['Date', formatDate(inspection.date)],
          ...(inspection.inspector && inspection.inspector !== '—' ? [['Inspector', inspection.inspector]] : []),
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
                <span className={f.flagged && /misalign/i.test(f.result) ? 'bg-yellow-200 px-1 font-semibold' : ''}>{f.result}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!compact && (
        <div className="mt-3 flex items-end justify-between text-neutral-500">
          <span>{inspection.summary || (inspection.inspector ? `Signed: ${inspection.inspector}` : '')}</span>
          <span className="font-serif italic">— handwritten notes on page 3 —</span>
        </div>
      )}
    </div>
  )
}

/** "Item: result; Item: result" → rows; a result may itself contain "; ". */
function quoteRows(quote: string): { item: string; result: string }[] {
  return quote
    .split(/;\s(?=[A-Z][^:;]{1,40}:\s)/)
    .map((part) => {
      const i = part.indexOf(': ')
      return i === -1 ? { item: '', result: part } : { item: part.slice(0, i), result: part.slice(i + 2) }
    })
}

/** A citation from the agent (/agent/ask `done`), rendered like the source document. */
export function CitationPaper({ citation }: { citation: Citation }) {
  const [name, ...rest] = citation.title.split(' · ')
  const meta = rest.join(' · ')

  if (citation.kind === 'inspection') {
    return (
      <div className="rounded-md border border-neutral-300 bg-white p-3 text-[11px] text-neutral-900 shadow-sm">
        <div className="flex items-baseline justify-between border-b border-neutral-400 pb-1.5">
          <span className="font-serif text-xs font-semibold">Inspection Report</span>
          <span className="text-neutral-500">{citation.title.replace(/^Inspection report /, '')}</span>
        </div>
        <div className="mt-2 font-medium">Findings</div>
        <table className="mt-1 w-full border border-neutral-300">
          <tbody>
            {quoteRows(citation.quote).map((r, i) => (
              <tr key={i} className="border-b border-neutral-300 last:border-0">
                {r.item && <td className="w-2/5 bg-neutral-100 px-2 py-1 align-top">{r.item}</td>}
                <td className="px-2 py-1" colSpan={r.item ? 1 : 2}>
                  <span className={/misalign/i.test(r.result) ? 'bg-yellow-200 px-1 font-semibold' : ''}>{r.result}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div className="rounded-md border border-neutral-300 bg-white p-3 text-[12px] leading-relaxed text-neutral-900 shadow-sm">
      <div className="border-b border-neutral-300 pb-1.5">
        <div className={`text-[13px] font-semibold ${citation.kind === 'work_orders' ? 'font-mono' : 'font-serif'}`}>{name}</div>
        {meta && <div className="mt-0.5 text-[11px] text-neutral-500">{citation.kind === 'work_orders' ? `Work order · ${meta}` : meta}</div>}
      </div>
      <p className={`mt-2 ${citation.kind === 'work_orders' ? 'font-mono text-[11px]' : ''}`}>
        <mark className="bg-yellow-200 px-0.5 text-neutral-900">{citation.quote}</mark>
      </p>
    </div>
  )
}
