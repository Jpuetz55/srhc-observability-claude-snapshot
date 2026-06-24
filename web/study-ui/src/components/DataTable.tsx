import type { StringRow } from '../api/types'

export function DataTable({ rows, columns, empty = 'No rows.' }: { rows: StringRow[]; columns: Array<[string, string]>; empty?: string }) {
  if (!rows.length) return <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">{empty}</p>
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800">
      <table className="min-w-full divide-y divide-slate-800 text-sm">
        <thead className="bg-slate-950/70 text-left text-xs uppercase tracking-wider text-slate-500">
          <tr>
            {columns.map(([key, label]) => (
              <th key={key} className="px-4 py-3 font-semibold">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800 bg-slate-900/60">
          {rows.map((row, rowIndex) => (
            <tr key={`${row.archive_id ?? row.test_run_id ?? rowIndex}`} className="hover:bg-slate-800/50">
              {columns.map(([key]) => (
                <td key={key} className="max-w-sm whitespace-nowrap px-4 py-3 text-slate-300">
                  {row[key] ?? ''}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
