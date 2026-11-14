import type { AgentSource, Inspection } from '../api/types'
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
                <span className={f.flagged && /misalign/i.test(f.result) ? 'bg-yellow-200 px-1 font-semibold' : ''}>{f.result}</span>
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

/** A retrieved manual passage (agent `sources` event), rendered like a page excerpt. */
export function SourcePassage({ source }: { source: AgentSource }) {
  return (
    <div className="rounded-md border border-neutral-300 bg-white p-3 text-[12px] leading-relaxed text-neutral-900 shadow-sm">
      <div className="border-b border-neutral-300 pb-1.5">
        <div className="font-serif text-[13px] font-semibold">{source.title || source.source}</div>
        <div className="mt-0.5 text-[11px] text-neutral-500">
          Page {source.page}
          {source.section ? ` · ${source.section}` : ''}
        </div>
      </div>
      <p className="mt-2">
        <mark className="bg-yellow-200 px-0.5 text-neutral-900">{source.snippet}</mark>
      </p>
      <div className="mt-2 font-mono text-[10px] text-neutral-400">{source.source}</div>
    </div>
  )
}
