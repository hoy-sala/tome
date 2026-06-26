import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowLeft, Search, Quote, StickyNote, Loader2, BookOpen,
  CalendarHeart, Copy, X, ChevronDown, Info, ChevronsDownUp, ChevronsUpDown,
} from 'lucide-react'
import { api } from '@/lib/api'
import { useToast } from '@/contexts/ToastContext'
import { cn } from '@/lib/utils'

interface Highlight {
  id: number
  book_id: number
  book_title: string
  book_author: string | null
  book_cover: string | null
  highlighted_text: string | null
  note: string | null
  chapter: string | null
  color: string | null
  datetime: string | null
  synced_at: string | null
}

interface HighlightsResponse {
  total: number
  books: number
  items: Highlight[]
}

interface BookGroup {
  book_id: number
  title: string
  author: string | null
  cover: string | null
  items: Highlight[]
}

const PAGE_SIZE = 15

// KOReader highlight colours → a dot tint. Unknown colours fall back to the
// primary accent. Dots only render when the library actually uses more than one
// colour (see `showDots`), so single-colour readers don't get noise.
const COLOR_TINT: Record<string, string> = {
  red: 'bg-red-500', orange: 'bg-orange-500', yellow: 'bg-yellow-500',
  green: 'bg-green-500', blue: 'bg-blue-500', purple: 'bg-purple-500',
  gray: 'bg-gray-400', grey: 'bg-gray-400',
}

function groupByBook(items: Highlight[]): BookGroup[] {
  const order: number[] = []
  const map = new Map<number, BookGroup>()
  for (const h of items) {
    let g = map.get(h.book_id)
    if (!g) {
      g = { book_id: h.book_id, title: h.book_title, author: h.book_author, cover: h.book_cover, items: [] }
      map.set(h.book_id, g)
      order.push(h.book_id)
    }
    g.items.push(h)
  }
  return order.map(id => map.get(id)!)
}

function groupToMarkdown(g: BookGroup): string {
  const lines = [`## ${g.title}${g.author ? ` — ${g.author}` : ''}`, '']
  for (const h of g.items) {
    if (h.chapter) lines.push(`*${h.chapter}*`)
    if (h.highlighted_text) lines.push(`> ${h.highlighted_text}`)
    if (h.note) lines.push('', `Note: ${h.note}`)
    lines.push('')
  }
  return lines.join('\n').trimEnd()
}

// Wrap case-insensitive matches of `q` in <mark>, leaving the rest as text.
function mark(text: string, q: string): ReactNode {
  if (!q) return text
  const esc = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${esc})`, 'ig'))
  return parts.map((p, i) =>
    p.toLowerCase() === q.toLowerCase()
      ? <mark key={i} className="bg-primary/25 text-foreground rounded px-0.5">{p}</mark>
      : <span key={i}>{p}</span>
  )
}

function parseKo(dt: string | null): Date | null {
  if (!dt) return null
  const d = new Date(dt.replace(' ', 'T'))
  return isNaN(d.getTime()) ? null : d
}

function shortDate(dt: string | null): string | null {
  const d = parseKo(dt)
  return d ? d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' }) : null
}

function fullInfo(h: Highlight): string {
  const parts: string[] = []
  const d = parseKo(h.datetime)
  if (d) parts.push(`Highlighted ${d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}`)
  if (h.chapter) parts.push(h.chapter)
  if (h.color) parts.push(`${h.color} highlight`)
  if (h.synced_at) {
    const s = new Date(h.synced_at)
    if (!isNaN(s.getTime())) parts.push(`Synced to Tome ${s.toLocaleDateString(undefined, { dateStyle: 'medium' })}`)
  }
  return parts.join('  ·  ')
}

function HighlightCard({ h, q, showDot }: { h: Highlight; q: string; showDot: boolean }) {
  const tint = h.color ? (COLOR_TINT[h.color.toLowerCase()] ?? 'bg-primary/50') : 'bg-primary/40'
  const date = shortDate(h.datetime)
  return (
    <li className="rounded-lg border border-border bg-muted/40 px-3.5 py-3">
      <div className="flex items-start justify-between gap-3 mb-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          {showDot && <span className={cn('w-2 h-2 rounded-full shrink-0', tint)} />}
          {h.chapter && (
            <p className="text-xs text-muted-foreground/70 truncate">{q ? mark(h.chapter, q) : h.chapter}</p>
          )}
        </div>
        {date && (
          <span
            className="flex items-center gap-1 text-[11px] text-muted-foreground/50 shrink-0 cursor-help"
            title={fullInfo(h)}
          >
            {date}
            <Info className="w-3 h-3" />
          </span>
        )}
      </div>
      {h.highlighted_text && (
        <p className="text-sm text-foreground leading-relaxed border-l-2 border-primary/40 pl-2.5">
          {q ? mark(h.highlighted_text, q) : h.highlighted_text}
        </p>
      )}
      {h.note && (
        <p className="mt-2 flex items-start gap-1.5 text-sm text-muted-foreground">
          <StickyNote className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="leading-relaxed">{q ? mark(h.note, q) : h.note}</span>
        </p>
      )}
    </li>
  )
}

export function HighlightsPage() {
  const { toast } = useToast()
  const [items, setItems] = useState<Highlight[]>([])
  const [total, setTotal] = useState(0)
  const [books, setBooks] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [onThisDay, setOnThisDay] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 250)
    return () => clearTimeout(t)
  }, [search])

  const buildParams = useCallback((offset: number) => {
    const p = new URLSearchParams()
    if (debounced) p.set('q', debounced)
    if (onThisDay) p.set('on_this_day', '1')
    p.set('limit', String(PAGE_SIZE))
    p.set('offset', String(offset))
    return p
  }, [debounced, onThisDay])

  // Reset + first page whenever the query/filter changes.
  useEffect(() => {
    const ctrl = new AbortController()
    setLoading(true)
    setError(null)
    api.get<HighlightsResponse>(`/annotations?${buildParams(0).toString()}`, ctrl.signal)
      .then(d => { setItems(d.items); setTotal(d.total); setBooks(d.books) })
      .catch(e => { if (e.name !== 'AbortError') setError(e.message ?? 'Failed to load') })
      .finally(() => setLoading(false))
    return () => ctrl.abort()
  }, [buildParams])

  async function loadMore() {
    setLoadingMore(true)
    try {
      const d = await api.get<HighlightsResponse>(`/annotations?${buildParams(items.length).toString()}`)
      setItems(prev => [...prev, ...d.items])
      setTotal(d.total)
    } catch (e) {
      toast.error((e as Error).message ?? 'Failed to load more')
    } finally {
      setLoadingMore(false)
    }
  }

  const groups = useMemo(() => groupByBook(items), [items])
  const hasMore = items.length < total
  // While searching, force every book open so matches are never hidden behind a
  // collapsed header. Manual collapse state is preserved and returns on clear.
  const searching = debounced.length > 0
  // Only show colour dots when the loaded highlights actually use >1 colour.
  const showDots = useMemo(
    () => new Set(items.map(i => i.color).filter(Boolean)).size >= 2,
    [items],
  )
  const allCollapsed = groups.length > 0 && groups.every(g => collapsed.has(g.book_id))

  function toggleBook(id: number) {
    setCollapsed(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  function toggleAll() {
    setCollapsed(allCollapsed ? new Set() : new Set(groups.map(g => g.book_id)))
  }

  async function copyAll() {
    // Export everything that matches, not just the loaded pages.
    const p = new URLSearchParams()
    if (debounced) p.set('q', debounced)
    if (onThisDay) p.set('on_this_day', '1')
    p.set('limit', '2000')
    const d = await api.get<HighlightsResponse>(`/annotations?${p.toString()}`)
    const md = groupByBook(d.items).map(groupToMarkdown).join('\n\n')
    await navigator.clipboard.writeText(md)
    toast.success(`Copied ${d.items.length} highlights as Markdown`)
  }

  async function copyGroup(g: BookGroup) {
    await navigator.clipboard.writeText(groupToMarkdown(g))
    toast.success(`Copied ${g.items.length} from “${g.title}”`)
  }

  const isEmpty = !loading && !error && groups.length === 0
  const neverSynced = isEmpty && !debounced && !onThisDay

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b border-border bg-background/80 backdrop-blur-sm safe-top">
        <div className="flex items-center gap-3 px-4 h-14 max-w-3xl mx-auto">
          <Link
            to="/"
            className="p-2 rounded-lg hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Quote className="w-4 h-4 text-muted-foreground shrink-0" />
            <span className="text-sm font-semibold">Highlights</span>
            {total > 0 && (
              <span className="text-xs text-muted-foreground/60 truncate">
                {total} from {books} book{books === 1 ? '' : 's'}
              </span>
            )}
          </div>
          {groups.length > 0 && (
            <button
              onClick={copyAll}
              title="Copy all as Markdown"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border hover:bg-muted transition-all"
            >
              <Copy className="w-3.5 h-3.5" />
              Export
            </button>
          )}
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6 space-y-5">
        {/* Controls */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/60" />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search your highlights…"
              className="w-full pl-9 pr-9 py-2 rounded-lg bg-muted/50 border border-border text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 rounded text-muted-foreground hover:text-foreground"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <button
            onClick={() => setOnThisDay(v => !v)}
            title="Highlights you made on this day in past years"
            className={cn(
              'flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border transition-all whitespace-nowrap',
              onThisDay
                ? 'bg-primary/10 border-primary/30 text-primary'
                : 'border-border text-muted-foreground hover:bg-muted'
            )}
          >
            <CalendarHeart className="w-3.5 h-3.5" />
            On this day
          </button>
          {groups.length > 0 && !searching && (
            <button
              onClick={toggleAll}
              title={allCollapsed ? 'Expand all' : 'Collapse all'}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border border-border text-muted-foreground hover:bg-muted transition-all whitespace-nowrap"
            >
              {allCollapsed ? <ChevronsUpDown className="w-3.5 h-3.5" /> : <ChevronsDownUp className="w-3.5 h-3.5" />}
              {allCollapsed ? 'Expand' : 'Collapse'}
            </button>
          )}
        </div>

        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          </div>
        ) : error ? (
          <div className="px-3 py-2 rounded-lg bg-destructive/10 border border-destructive/20 text-sm text-destructive">
            {error}
          </div>
        ) : isEmpty ? (
          <div className="flex flex-col items-center justify-center text-center py-20 gap-3 text-muted-foreground">
            <Quote className="w-8 h-8 opacity-40" />
            {neverSynced ? (
              <>
                <p className="text-sm font-medium text-foreground">No highlights yet</p>
                <p className="text-xs max-w-xs leading-relaxed">
                  Highlights and notes you make in KOReader sync here automatically.
                  Highlight a passage on your device, then sync — it’ll show up in this
                  commonplace book.
                </p>
              </>
            ) : (
              <p className="text-sm">
                {onThisDay ? 'Nothing highlighted on this day — yet.' : 'No highlights match your search.'}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            {groups.map(g => {
              const isCollapsed = !searching && collapsed.has(g.book_id)
              return (
                <section key={g.book_id} className="animate-card-appear">
                  <div className="flex items-center gap-3 mb-3">
                    <Link to={`/books/${g.book_id}`} className="shrink-0">
                      <div className="w-10 h-14 rounded bg-muted overflow-hidden flex items-center justify-center">
                        {g.cover ? (
                          <img
                            src={g.cover}
                            alt=""
                            className="w-full h-full object-cover"
                            onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
                          />
                        ) : (
                          <BookOpen className="w-4 h-4 text-muted-foreground" />
                        )}
                      </div>
                    </Link>
                    <button
                      onClick={() => toggleBook(g.book_id)}
                      className="flex-1 min-w-0 flex items-center gap-2 text-left group"
                    >
                      <ChevronDown
                        className={cn('w-4 h-4 text-muted-foreground/60 shrink-0 transition-transform', isCollapsed && '-rotate-90')}
                      />
                      <span className="min-w-0">
                        <span className="block font-display text-base text-foreground group-hover:text-primary transition-colors line-clamp-1">
                          {g.title}
                        </span>
                        {g.author && <span className="block text-xs text-muted-foreground truncate">{g.author}</span>}
                      </span>
                      <span className="text-xs text-muted-foreground/60 shrink-0 ml-auto">
                        {g.items.length}
                      </span>
                    </button>
                    <button
                      onClick={() => copyGroup(g)}
                      title="Copy this book’s highlights as Markdown"
                      className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors shrink-0"
                    >
                      <Copy className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  {/* grid-rows 1fr↔0fr gives a smooth height collapse without measuring. */}
                  <div className={cn('grid transition-[grid-template-rows] duration-300 ease-out', isCollapsed ? 'grid-rows-[0fr]' : 'grid-rows-[1fr]')}>
                    <div className="overflow-hidden">
                      <ul className="space-y-2.5">
                        {g.items.map(h => <HighlightCard key={h.id} h={h} q={debounced} showDot={showDots} />)}
                      </ul>
                    </div>
                  </div>
                </section>
              )
            })}

            {hasMore && (
              <div className="flex justify-center pt-1">
                <button
                  onClick={loadMore}
                  disabled={loadingMore}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border border-border hover:bg-muted transition-all disabled:opacity-60"
                >
                  {loadingMore ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  Load more ({total - items.length} left)
                </button>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
