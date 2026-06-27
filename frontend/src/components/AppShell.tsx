import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Menu, Search, X } from 'lucide-react'
import { useAuth, isMember } from '@/contexts/AuthContext'
import { api } from '@/lib/api'
import type { Library, SavedFilter } from '@/lib/books'
import { Sidebar } from '@/components/Sidebar'
import { TomeMark } from '@/components/TomeMark'
import { SyncStatusBadge } from '@/components/SyncStatusBadge'
import { NotificationBell } from '@/components/NotificationBell'
import { UploadModal } from '@/components/UploadModal'

/**
 * The shared application shell — the same top navbar (Tome wordmark) + persistent
 * Sidebar (docked on desktop, drawer on mobile) that the dashboard uses, so the
 * standalone pages (Stats, Highlights, Wishlist, Bindery) get the *real* nav
 * instead of a stripped-down clone. The page renders its own content as children;
 * `actions` slots page-specific controls into the navbar's right side.
 *
 * Home / All Books / Series in the sidebar navigate back to the dashboard; the
 * active section item (Stats/Highlights/…) highlights itself by route.
 */
export function AppShell({
  children,
  actions,
}: {
  children: ReactNode
  actions?: ReactNode
}) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [libraries, setLibraries] = useState<Library[]>([])
  const [savedFilters, setSavedFilters] = useState<SavedFilter[]>([])
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [searchInput, setSearchInput] = useState('')

  // Global library search from any page: Enter jumps to the dashboard's book
  // results (it never live-yanks you off the current page mid-type).
  function submitSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = searchInput.trim()
    navigate(q ? `/?tab=books&q=${encodeURIComponent(q)}` : '/?tab=books')
  }

  const loadLibraries = () => { api.get<Library[]>('/libraries').then(setLibraries).catch(() => {}) }
  const loadSavedFilters = () => { api.get<SavedFilter[]>('/saved-filters').then(setSavedFilters).catch(() => {}) }
  useEffect(() => { loadLibraries(); loadSavedFilters() }, [])

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      <header className="border-b border-border bg-card/50 backdrop-blur-sm sticky top-0 z-20 shrink-0 safe-top">
        <div className="px-4 h-14 flex items-center gap-3">
          <button
            className="md:hidden flex items-center justify-center w-8 h-8 text-muted-foreground hover:text-foreground transition-colors rounded-lg hover:bg-muted shrink-0"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-2 mr-2 shrink-0 group cursor-default">
            <TomeMark className="w-5 h-5 text-primary logo-bob" strokeWidth={7} />
            <span className="font-semibold text-sm">Tome</span>
          </div>
          <form onSubmit={submitSearch} className="relative flex-1 sm:max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
            <input
              className="w-full h-8 pl-9 pr-8 rounded-lg bg-muted border border-border text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="Search books…"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
            />
            {searchInput && (
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label="Clear search"
                onClick={() => setSearchInput('')}
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </form>
          <div className="flex items-center gap-1.5 ml-auto">
            {actions}
            <SyncStatusBadge />
            <NotificationBell />
            {isMember(user) && (
              <button
                onClick={() => setUploadOpen(true)}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border border-border bg-card hover:bg-muted transition-all touch-feedback"
              >
                <span className="hidden sm:inline">Upload</span>
              </button>
            )}
          </div>
        </div>
      </header>

      <UploadModal
        isOpen={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onDone={() => {}}
        onWishMatches={() => {}}
      />

      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          libraries={libraries}
          savedFilters={savedFilters}
          activeTab="none"
          onLibrariesChange={loadLibraries}
          onSavedFiltersChange={loadSavedFilters}
          onOpenSeriesView={() => navigate('/?tab=series')}
          onOpenHomeView={() => navigate('/')}
          mobileOpen={mobileSidebarOpen}
          onMobileClose={() => setMobileSidebarOpen(false)}
        />
        <main className="flex-1 overflow-y-auto min-w-0">{children}</main>
      </div>
    </div>
  )
}
