import { useState } from 'react'
import { Menu, Plus } from 'lucide-react'
import ChatWindow from './components/ChatWindow/ChatWindow'
import Sidebar from './components/Sidebar/Sidebar'
import MemoryPanel from './components/MemoryPanel/MemoryPanel'

const DEFAULT_USER_ID = 'ani.mallya'
const LEGACY_DEFAULT_USER_ID = 'dev_user_001'

const getInitialUserId = () => {
  const stored = localStorage.getItem('anios_user_id')
  if (stored && stored !== LEGACY_DEFAULT_USER_ID) return stored

  localStorage.setItem('anios_user_id', DEFAULT_USER_ID)
  localStorage.removeItem('anios_conversation_id')
  return DEFAULT_USER_ID
}

function App() {
  const [isSidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768)
  const [activeView, setActiveView] = useState<'chat' | 'memory'>('chat')
  const [userId, setUserId] = useState(getInitialUserId)
  const [conversationId, setConversationId] = useState(() => {
    const stored = localStorage.getItem('anios_conversation_id')
    if (stored) return stored
    const created = crypto.randomUUID()
    localStorage.setItem('anios_conversation_id', created)
    return created
  })

  const rotateConversation = () => {
    const created = crypto.randomUUID()
    setConversationId(created)
    localStorage.setItem('anios_conversation_id', created)
  }

  const startNewConversation = () => {
    rotateConversation()
    setActiveView('chat')
  }

  const updateUserId = (nextUserId: string) => {
    const normalized = nextUserId.trim()
    if (!normalized || normalized === userId) return
    setUserId(normalized)
    localStorage.setItem('anios_user_id', normalized)
    rotateConversation()
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
            key={`${userId}:${conversationId}`}
            userId={userId}
            conversationId={conversationId}
          />
        </div>
        {activeView === 'memory' && (
          <MemoryPanel userId={userId} onUserIdChange={updateUserId} />
        )}
      </main>
    </div>
  )
}

export default App
