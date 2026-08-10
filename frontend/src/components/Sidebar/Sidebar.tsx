import React, { useEffect, useState } from 'react'
import { deleteConversation, listConversations, type ConversationSummary } from '../../services/api'
import ThemeToggle from '../ThemeToggle/ThemeToggle'
import { Bot, BrainCircuit, Image, LogOut, MessageCircle, Presentation, ShieldCheck, Trash2 } from 'lucide-react'

interface SidebarProps {
  activeView: 'chat' | 'memory' | 'artifacts' | 'presentations' | 'agents' | 'admin'
  onViewChange: (view: 'chat' | 'memory' | 'artifacts' | 'presentations' | 'agents' | 'admin') => void
  // The operator surface is hidden for a guest. The server refuses it anyway;
  // this keeps the workspace from advertising something they cannot use.
  isAdmin?: boolean
  userId?: string
  activeConversationId?: string
  onOpenConversation?: (conversationId: string) => void
  onNewConversation?: () => void
  canSignOut?: boolean
  onSignOut?: () => void
}

const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onViewChange,
  isAdmin = false,
  userId,
  activeConversationId,
  onOpenConversation,
  onNewConversation,
  canSignOut = false,
  onSignOut,
}) => {
  const [history, setHistory] = useState<ConversationSummary[]>([])
  // A failed load and an empty history looked identical, which is how a
  // missing sidebar got reported as missing data.
  const [historyFailed, setHistoryFailed] = useState(false)

  // Removed from the list straight away rather than after a reload: the row is
  // gone from the server, so leaving it on screen would be a lie.
  const removeConversation = async (conversationId: string) => {
    if (!userId) return
    if (!window.confirm('Delete this conversation? This cannot be undone.')) return
    try {
      await deleteConversation(userId, conversationId)
      setHistory(rows => rows.filter(row => row.conversation_id !== conversationId))
      if (conversationId === activeConversationId) onNewConversation?.()
    } catch {
      // Leave the row: a failed delete that vanishes from the list reads as
      // success and the conversation reappears on the next load.
    }
  }

  // Loaded from the server rather than local storage, so history follows the
  // account onto a second device instead of living in one browser. Reloaded
  // when the active conversation changes, which is when a new one appears.
  useEffect(() => {
    if (!userId) return
    let cancelled = false
    void listConversations(userId)
      .then(rows => {
        if (cancelled) return
        setHistory(rows)
        setHistoryFailed(false)
      })
      // A history that will not load must not take the workspace down with it.
      .catch(() => {
        if (cancelled) return
        setHistory([])
        setHistoryFailed(true)
      })
    return () => { cancelled = true }
    // Deliberately not depending on the callbacks: they are defined inline
    // by the parent, so a new identity every render would refetch history
    // in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, activeConversationId])

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-[264px] flex-none flex-col border-r border-black/[0.06] bg-white px-4 py-5 backdrop-blur-xl md:static md:z-auto md:w-[232px] md:bg-white/72">
      <div className="mb-8 px-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#86868b]">Workspace</p>
      </div>
      <nav className="space-y-2" aria-label="Primary navigation">
        <button
          aria-label="Conversations"
          onClick={() => onViewChange('chat')}
          className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'chat' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
        >
          <MessageCircle size={19} className={activeView === 'chat' ? 'text-[#0071e3]' : ''} />
          <span className="inline">Conversations</span>
        </button>
        <button
          aria-label="Visual artifacts"
          onClick={() => onViewChange('artifacts')}
          className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'artifacts' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
        >
          <Image size={19} className={activeView === 'artifacts' ? 'text-[#0071e3]' : ''} />
          <span className="inline">Artifacts</span>
        </button>
        <button
          aria-label="Presentations"
          onClick={() => onViewChange('presentations')}
          className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'presentations' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
        >
          <Presentation size={19} className={activeView === 'presentations' ? 'text-[#0071e3]' : ''} />
          <span className="inline">Presentations</span>
        </button>
        <button
          aria-label="Agents"
          onClick={() => onViewChange('agents')}
          className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'agents' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
        >
          <Bot size={19} className={activeView === 'agents' ? 'text-[#0071e3]' : ''} />
          <span className="inline">Agents</span>
        </button>
        <button
          aria-label="Memory"
          onClick={() => onViewChange('memory')}
          className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'memory' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
        >
          <BrainCircuit size={19} className={activeView === 'memory' ? 'text-[#0071e3]' : ''} />
          <span className="inline">Memory</span>
        </button>
        {isAdmin && (
          <button
            aria-label="Operator"
            onClick={() => onViewChange('admin')}
            className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'admin' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
          >
            <ShieldCheck size={19} className={activeView === 'admin' ? 'text-[#0071e3]' : ''} />
            <span className="inline">Operator</span>
          </button>
        )}
      </nav>
      {activeView === 'chat' && onOpenConversation && (
        <div className="mt-6 flex min-h-0 flex-1 flex-col">
          <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#86868b]">
            History
          </p>
          <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
            {history.length === 0 && historyFailed && (
              <p className="px-3 text-[12px] text-[#b42318]">
                Could not load your chats. They are safe — try again shortly.
              </p>
            )}
            {history.length === 0 && !historyFailed && (
              // Silence here reads as a broken sidebar. An account with no
              // chats yet should be told that is what it is looking at.
              <p className="px-3 text-[12px] text-[#86868b]">
                Nothing yet. Your chats appear here.
              </p>
            )}
            {history.map(row => (
              <div
                key={row.conversation_id}
                className={`group flex items-center rounded-lg pr-1 transition ${
                  row.conversation_id === activeConversationId
                    ? 'bg-[#0071e3]/10'
                    : 'hover:bg-black/[0.04]'
                }`}
              >
                <button
                  type="button"
                  onClick={() => onOpenConversation(row.conversation_id)}
                  title={row.title}
                  className={`min-w-0 flex-1 truncate px-3 py-1.5 text-left text-[13px] ${
                    row.conversation_id === activeConversationId
                      ? 'text-[#0071e3]'
                      : 'text-[#6e6e73]'
                  }`}
                >
                  {row.title || 'Untitled'}
                </button>
                <button
                  type="button"
                  onClick={() => void removeConversation(row.conversation_id)}
                  aria-label={`Delete conversation ${row.title || 'Untitled'}`}
                  title="Delete"
                  className="flex-none rounded p-1 text-[#86868b] opacity-0 transition hover:text-[#b42318] focus:opacity-100 group-hover:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="mt-auto space-y-3">
        {/* Drawer width only: from md the header carries this control, and
            rendering both would put two on screen at once — the same mistake
            that once produced two sign-out buttons. Kept outside the account
            section because that section only exists when sign-out does, and a
            user with no account still has a theme. */}
        <ThemeToggle
          withLabel
          className="flex h-10 w-full items-center gap-3 rounded-xl bg-[#f5f5f7] px-3 text-sm font-medium text-[#1d1d1f] hover:bg-white md:hidden"
        />
        {canSignOut && onSignOut && (
          // Keep account identity beside the exit action so a phone user can
          // verify which Scout profile is active before changing its settings.
          //
          // Drawer widths only. From md this sidebar is part of the layout and
          // sits beside a header that carries both, so rendering them here too
          // put two sign-out buttons on screen at once.
          <section
            aria-label="Account controls"
            className="rounded-2xl bg-[#f5f5f7] px-3 py-3 md:hidden"
          >
            <p className="truncate px-1 text-xs text-[#6e6e73]">Signed in as {userId}</p>
            <button
              type="button"
              onClick={onSignOut}
              className="mt-2 flex h-10 w-full items-center gap-3 rounded-xl px-3 text-sm font-medium text-[#1d1d1f] hover:bg-white"
            >
              <LogOut size={17} />
              <span>Sign out</span>
            </button>
          </section>
        )}
        <div className="hidden rounded-2xl bg-[#f5f5f7] px-4 py-3 lg:block">
          <p className="text-xs font-medium text-[#1d1d1f]">Local by default</p>
          <p className="mt-0.5 text-[11px] leading-4 text-[#86868b]">Your assistant runs on your machine.</p>
        </div>
      </div>
    </aside>
  )
}

export default Sidebar
