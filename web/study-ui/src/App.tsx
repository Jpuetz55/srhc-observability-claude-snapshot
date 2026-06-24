import { useEffect, useState } from 'react'
import { getRfSummary } from './api/client'
import type { AppConfig } from './api/types'
import { Button } from './components/Button'
import { MediaQoeStudy } from './pages/MediaQoeStudy'
import { RfValidationStudy } from './pages/RfValidationStudy'
import { VoceraMulticastStudy } from './pages/VoceraMulticastStudy'

type Page = 'rf' | 'icap' | 'multicast'

const defaultConfig: AppConfig = {
  scope: 'vocera_badge',
  user: 'study_web',
  grafana: { basePath: '/grafana', orgId: '1', theme: 'dark', proxyEnabled: true, panels: {} }
}

function App() {
  const [page, setPage] = useState<Page>('rf')
  const [config, setConfig] = useState<AppConfig>(defaultConfig)

  useEffect(() => {
    getRfSummary()
      .then((summary) => setConfig(summary.config))
      .catch(() => setConfig(defaultConfig))
  }, [])

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.16),_transparent_30%),linear-gradient(180deg,_#020617_0%,_#0f172a_100%)] text-slate-100">
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">SRHC observability</p>
            <p className="mt-1 text-lg font-semibold text-slate-100">Study Workflow Console</p>
          </div>
          <nav className="flex gap-2">
            <Button variant={page === 'rf' ? 'primary' : 'secondary'} onClick={() => setPage('rf')}>
              RF validation
            </Button>
            <Button variant={page === 'icap' ? 'primary' : 'secondary'} onClick={() => setPage('icap')}>
              ICAP QoE
            </Button>
            <Button variant={page === 'multicast' ? 'primary' : 'secondary'} onClick={() => setPage('multicast')}>
              Vocera multicast
            </Button>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {page === 'rf' && <RfValidationStudy />}
        {page === 'icap' && <MediaQoeStudy config={config} />}
        {page === 'multicast' && <VoceraMulticastStudy />}
      </main>
    </div>
  )
}

export default App
