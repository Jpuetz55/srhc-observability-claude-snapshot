import type { ButtonHTMLAttributes, ReactNode } from 'react'

const variants = {
  primary: 'bg-cyan-400 text-slate-950 hover:bg-cyan-300 focus-visible:outline-cyan-200',
  secondary: 'bg-slate-800 text-slate-100 hover:bg-slate-700 focus-visible:outline-slate-500',
  danger: 'bg-rose-500 text-white hover:bg-rose-400 focus-visible:outline-rose-300',
  ghost: 'bg-transparent text-slate-300 hover:bg-slate-800 focus-visible:outline-slate-500'
}

export function Button({
  children,
  variant = 'primary',
  className = '',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode; variant?: keyof typeof variants }) {
  return (
    <button
      className={`rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${variants[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
