import { useEffect, useState } from 'react'
import { Menu, Plus } from 'lucide-react'
import ChatWindow from './components/ChatWindow/ChatWindow'
import Sidebar from './components/Sidebar/Sidebar'
import MemoryPanel from './components/MemoryPanel/MemoryPanel'
import ArtifactPanel from './components/ArtifactPanel/ArtifactPanel'

const DEFAULT_USER_ID = 'ani.mallya'
const LEGACY_DEFAULT_USER_ID = 'dev_user_001'

interface ActiveConversation {
  id: string;
  restore: boolean;
}

interface ActiveSession {
  userId: string;
  conversation: ActiveConversation;
}

// Read one initial session without mutating storage during React initialization.
const getInitialSession = (): ActiveSession => {
  const storedUser = localStorage.getItem('anios_user_id')
  const migrateUser = !storedUser || storedUser === LEGACY_DEFAULT_USER_ID
  const userId = migrateUser ? DEFAULT_USER_ID : storedUser as string
  const storedConversation = migrateUser
    ? null
    : localStorage.getItem('anios_conversation_id')
  return {
    userId,
    conversation: storedConversation
      ? { id: storedConversation, restore: true }
      : { id: crypto.randomUUID(), restore: false },
  }
}

// Coordinate the active user, conversation, and primary application view.
function App() {
  const [isSidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768)
  const [activeView, setActiveView] = useState<'chat' | 'memory' | 'artifacts'>('chat')
  const [session, setSession] = useState(getInitialSession)
  const { userId, conversation } = session

  // Persist the committed session after React finishes initialization.
  useEffect(() => {
    localStorage.setItem('anios_user_id', userId)
    localStorage.setItem('anios_conversation_id', conversation.id)
  }, [conversation.id, userId])

  // Start a new empty conversation and persist its identifier for later reloads.
  const rotateConversation = () => {
    const created = crypto.randomUUID()
    setSession(current => ({
      ...current,
      conversation: { id: created, restore: false },
    }))
    localStorage.setItem('anios_conversation_id', created)
  }

  // Open a new chat without changing the active user.
  const startNewConversation = () => {
    rotateConversation()
    setActiveView('chat')
  }

  // Change the logical local user and isolate them in a new conversation.
  const updateUserId = (nextUserId: string) => {
    const normalized = nextUserId.trim()
    if (!normalized || normalized === userId) return
    const created = crypto.randomUUID()
    setSession({
      userId: normalized,
      conversation: { id: created, restore: false },
    })
    localStorage.setItem('anios_user_id', normalized)
    localStorage.setItem('anios_conversation_id', created)
  }

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-[#f5f5f7] text-[#1d1d1f]">
      {isSidebarOpen && (
        <Sidebar
          activeView={activeView}
          onViewChange={setActiveView}
        />
      )}
      <main className="relative flex min-w-0 flex-1 flex-col bg-[#f5f5f7]">
        <header className="z-10 flex h-16 flex-none items-center justify-between border-b border-black/[0.06] bg-white/80 px-4 backdrop-blur-xl md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <span className="anios-wordmark flex h-9 w-9 flex-none items-center justify-center rounded-xl text-sm font-semibold text-white">A</span>
            <div className="min-w-0">
              <h1 className="truncate text-[17px] font-semibold tracking-[-0.02em]">AniOS</h1>
              <p className="hidden text-xs text-[#6e6e73] sm:block">Local intelligence</p>
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
            <button
              aria-label={isSidebarOpen ? 'Hide Sidebar' : 'Show Sidebar'}
              onClick={() => setSidebarOpen(!isSidebarOpen)}
              className="flex h-10 w-10 items-center justify-center rounded-full border border-black/[0.08] bg-white text-[#1d1d1f] hover:bg-[#f5f5f7]"
            >
              <Menu size={18} />
            </button>
          </div>
        </header>
        <div className={activeView === 'chat' ? 'flex flex-1 min-h-0' : 'hidden'}>
          <ChatWindow
            key={`${userId}:${conversation.id}`}
            userId={userId}
            conversationId={conversation.id}
            restoreConversation={conversation.restore}
          />
        </div>
        {activeView === 'memory' && (
          <MemoryPanel userId={userId} onUserIdChange={updateUserId} />
        )}
        {activeView === 'artifacts' && <ArtifactPanel userId={userId} />}
      </main>
    </div>
  )
}

export default App
