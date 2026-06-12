import { useEffect, useState } from 'react'
import { useKosyncStatus } from '@/hooks/useKosyncStatus'
import { cn } from '@/lib/utils'

const FRESH_MS = 5 * 60_000
const RECENT_MS = 30 * 60_000

function formatRelative(iso: string | null): string {
  if (!iso) return 'Never'
  const ts = new Date(iso).getTime()
  if (Number.isNaN(ts)) return 'Never'
  const diff = Date.now() - ts
  if (diff < 60_000) return 'Just synced'
  const mins = Math.floor(diff / 60_000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days}d ago`
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function dotColor(diff: number): string {
  if (diff < FRESH_MS) return 'bg-success'
  if (diff < RECENT_MS) return 'bg-warning'
  return 'bg-muted-foreground/40'
}

export function SyncStatusBadge() {
  const status = useKosyncStatus()
  const [, force] = useState(0)

  // Re-render every 60s so the relative label drifts forward even without new data
  useEffect(() => {
    const id = window.setInterval(() => force(n => n + 1), 60_000)
    return () => window.clearInterval(id)
  }, [])

  if (!status || !status.linked) return null

  const ts = status.lastSync ? new Date(status.lastSync).getTime() : 0
  const diff = ts ? Date.now() - ts : Infinity
  const label = formatRelative(status.lastSync)
  const tooltip = status.lastDevice
    ? `Last sync from ${status.lastDevice} · ${status.syncedDocuments} book${status.syncedDocuments === 1 ? '' : 's'} tracked`
    : `${status.syncedDocuments} book${status.syncedDocuments === 1 ? '' : 's'} tracked`

  return (
    <div
      title={`${label} — ${tooltip}`}
      className="inline-flex items-center gap-1.5 h-7 px-1.5 sm:px-2 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-colors cursor-default select-none"
      aria-label={`KOReader sync: ${label}. ${tooltip}`}
    >
      <span className={cn('w-2 h-2 sm:w-1.5 sm:h-1.5 rounded-full', dotColor(diff))} />
      <span className="font-medium tabular-nums hidden sm:inline">{label}</span>
    </div>
  )
}
