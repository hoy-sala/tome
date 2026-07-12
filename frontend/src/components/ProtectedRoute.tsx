import { Navigate } from 'react-router-dom'
import { useAuth, isMember, isAdmin } from '@/contexts/AuthContext'

type Role = 'member' | 'admin'

export function ProtectedRoute({ children, minRole }: { children: React.ReactNode; minRole?: Role }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (minRole === 'admin' && !isAdmin(user)) {
    return <Navigate to="/" replace />
  }

  if (minRole === 'member' && !isMember(user)) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}
