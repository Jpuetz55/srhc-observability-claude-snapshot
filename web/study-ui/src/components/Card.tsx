import type { ReactNode } from 'react'

export function Card({ title, eyebrow, children, actions, className = '' }: { title?: string; eyebrow?: string; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`rounded-2xl border border-slate-800 bg-slate-900/80 p-5 shadow-xl shadow-black/10 ${className}`}>
      {(title || eyebrow || actions) && (
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">{eyebrow}</p>}
            {title && <h2 className="mt-1 text-lg font-semibold text-slate-100">{title}</h2>}
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  )
}
