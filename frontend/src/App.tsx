import { useEffect, useState } from 'react'
import { LogOut, Menu, Plus } from 'lucide-react'
import AgentPanel from './components/AgentPanel/AgentPanel'
import AdminPanel from './components/AdminPanel/AdminPanel'
import ArtifactPanel from './components/ArtifactPanel/ArtifactPanel'
import ChatWindow from './components/ChatWindow/ChatWindow'
import LoginScreen from './components/LoginScreen/LoginScreen'
import MemoryPanel from './components/MemoryPanel/MemoryPanel'
import PresentationPanel from './components/PresentationPanel/PresentationPanel'
import Sidebar from './components/Sidebar/Sidebar'
import {
  getAuthSession,
  logout,
  type AuthSession,
} from './services/api'

interface ActiveConversation {
  id: string;
  restore: boolean;
}

// Restore only the conversation identifier previously used by this signed-in user.
const getInitialConversation = (userId: string): ActiveConversation => {
  const scopedKey = `anios_conversation_id:${userId}`
  const stored = localStorage.getItem(scopedKey)
  if (stored) return { id: stored, restore: true }
  const legacy = userId === 'ani.mallya'
    ? localStorage.getItem('anios_conversation_id')
    : null
  if (legacy) {
    localStorage.setItem(scopedKey, legacy)
    return { id: legacy, restore: true }
  }
  return { id: crypto.randomUUID(), restore: false }
}

interface AuthenticatedAppProps {
  auth: AuthSession;
  onSignedOut: () => void;
}

// Render the private workspace using only the server-authenticated user identity.
const AuthenticatedApp = ({ auth, onSignedOut }: AuthenticatedAppProps) => {
  const userId = auth.user_id
  const [isSidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768)
  const [activeView, setActiveView] = useState<'chat' | 'memory' | 'artifacts' | 'presentations' | 'agents' | 'admin'>('chat')
  const [conversation, setConversation] = useState(() => getInitialConversation(userId))
  const [logoutError, setLogoutError] = useState('')

  // Persist the active conversation separately for each authenticated account.
  useEffect(() => {
    localStorage.setItem(`anios_conversation_id:${userId}`, conversation.id)
  }, [conversation.id, userId])

  // Reopen a stored conversation. `restore: true` is what makes the window load
  // its persisted turns rather than starting empty on the same id.
  const openConversation = (conversationId: string) => {
    setConversation({ id: conversationId, restore: true })
    setActiveView('chat')
  }

  // Start a new empty conversation without changing the signed-in owner.
  const rotateConversation = () => {
    setConversation({ id: crypto.randomUUID(), restore: false })
  }

  // Open a new chat while retaining the authenticated account boundary.
  const startNewConversation = () => {
    rotateConversation()
    setActiveView('chat')
  }

  // Revoke the server session before returning to the login screen.
  const signOut = async () => {
    setLogoutError('')
    try {
      await logout()
      onSignedOut()
    } catch (reason) {
      setLogoutError(reason instanceof Error ? reason.message : 'Unable to sign out.')
    }
  }

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-[#f5f5f7] text-[#1d1d1f]">
      {isSidebarOpen && (
        <Sidebar
          isAdmin={auth.is_admin}
          activeView={activeView}
          onViewChange={setActiveView}
          userId={userId}
          activeConversationId={conversation.id}
          onOpenConversation={openConversation}
        />
      )}
      <main className="relative flex min-w-0 flex-1 flex-col bg-[#f5f5f7]">
        <header className="z-10 flex h-16 flex-none items-center justify-between border-b border-black/[0.06] bg-white/80 px-4 backdrop-blur-xl md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <span className="anios-wordmark flex h-9 w-9 flex-none items-center justify-center rounded-xl text-sm font-semibold text-white">A</span>
            <div className="min-w-0">
              <h1 className="truncate text-[17px] font-semibold tracking-[-0.02em]">AniOS</h1>
              <p className="hidden text-xs text-[#6e6e73] sm:block">Signed in as {userId}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              aria-label="New conversation"
              onClick={startNewConversation}
              className="flex h-10 items-center gap-2 rounded-full bg-[#1d1d1f] px-3.5 text-sm font-medium text-white hover:bg-black sm:px-4"
            >
              <Plus size={17} strokeWidth={2.25} />
              <span className="hidden sm:inline">New chat</span>
            </button>
            {auth.authentication_required && (
              <button
                aria-label="Sign out"
                onClick={() => void signOut()}
                className="flex h-10 w-10 items-center justify-center rounded-full border border-black/[0.08] bg-white text-[#1d1d1f] hover:bg-[#f5f5f7]"
              >
                <LogOut size={17} />
              </button>
            )}
            <button
              aria-label={isSidebarOpen ? 'Hide Sidebar' : 'Show Sidebar'}
              onClick={() => setSidebarOpen(!isSidebarOpen)}
              className="flex h-10 w-10 items-center justify-center rounded-full border border-black/[0.08] bg-white text-[#1d1d1f] hover:bg-[#f5f5f7]"
            >
              <Menu size={18} />
            </button>
          </div>
        </header>
        {logoutError && <p role="alert" className="bg-[#fff1f0] px-4 py-2 text-sm text-[#b42318]">{logoutError}</p>}
        <div className={activeView === 'chat' ? 'flex flex-1 min-h-0' : 'hidden'}>
          <ChatWindow
            key={`${userId}:${conversation.id}`}
            userId={userId}
            conversationId={conversation.id}
            restoreConversation={conversation.restore}
          />
        </div>
        {activeView === 'memory' && <MemoryPanel userId={userId} />}
        {activeView === 'artifacts' && <ArtifactPanel userId={userId} />}
        {/* Guarded twice: hidden unless the session says operator, and every
            route behind it re-checks against the database. */}
        {activeView === 'admin' && auth.is_admin && <AdminPanel />}
        {activeView === 'agents' && (
          <AgentPanel userId={userId} onOpenView={setActiveView} />
        )}
        {activeView === 'presentations' && (
          <PresentationPanel
            userId={userId}
            conversationId={conversation.id}
          />
        )}
      </main>
    </div>
  )
}

// Gate the entire application on the backend's revocable authenticated session.
function App() {
  const [auth, setAuth] = useState<AuthSession | null | undefined>(undefined)
  const [startupError, setStartupError] = useState('')

  // Resolve the current cookie session before mounting any private workspace view.
  useEffect(() => {
    void getAuthSession()
      .then(setAuth)
      .catch(reason => {
        setStartupError(reason instanceof Error ? reason.message : 'Unable to reach AniOS.')
        setAuth(null)
      })
  }, [])

  // Return to login whenever any API request reports an expired session.
  useEffect(() => {
    const handleUnauthorized = () => setAuth(null)
    window.addEventListener('anios:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('anios:unauthorized', handleUnauthorized)
  }, [])

  if (auth === undefined) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-[#f5f5f7] text-[#6e6e73]">
        <p role="status">Opening AniOS…</p>
      </main>
    )
  }
  if (auth === null) {
    return (
      <>
        {startupError && <p role="alert" className="fixed inset-x-0 top-0 z-10 bg-[#fff1f0] p-3 text-center text-sm text-[#b42318]">{startupError}</p>}
        <LoginScreen onAuthenticated={session => {
          setStartupError('')
          setAuth(session)
        }} />
      </>
    )
  }
  return <AuthenticatedApp key={auth.user_id} auth={auth} onSignedOut={() => setAuth(null)} />
}

export default App
