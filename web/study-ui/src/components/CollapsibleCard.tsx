import { useState, type ReactNode } from 'react'

export function CollapsibleCard({
  title,
  eyebrow,
  children,
  actions,
  defaultOpen = true
}: {
  title?: string
  eyebrow?: string
  children: ReactNode
  actions?: ReactNode
  defaultOpen?: boolean
}) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5 shadow-xl shadow-black/10">
      {(title || eyebrow || actions) && (
        <div
          className="mb-4 flex flex-col gap-3 cursor-pointer sm:flex-row sm:items-start sm:justify-between hover:opacity-80 transition-opacity"
          onClick={() => setIsOpen(!isOpen)}
        >
          <div className="flex items-center gap-2">
            <div className="text-cyan-400 text-lg font-bold leading-none transition-transform" style={{ transform: isOpen ? 'rotate(0deg)' : 'rotate(-90deg)' }}>
              ▼
            </div>
            <div>
              {eyebrow && <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">{eyebrow}</p>}
              {title && <h2 className="mt-1 text-lg font-semibold text-slate-100">{title}</h2>}
            </div>
          </div>
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </div>
      )}
      {isOpen && <div>{children}</div>}
    </section>
  )
}
