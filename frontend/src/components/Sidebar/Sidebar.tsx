import React from 'react'
import { BrainCircuit, MessageCircle } from 'lucide-react'

interface SidebarProps {
  activeView: 'chat' | 'memory'
  onViewChange: (view: 'chat' | 'memory') => void
}

const Sidebar: React.FC<SidebarProps> = ({ activeView, onViewChange }) => {
  return (
    <aside className="flex w-[76px] flex-none flex-col border-r border-black/[0.06] bg-white/72 px-3 py-5 backdrop-blur-xl lg:w-[232px] lg:px-4">
      <div className="mb-8 hidden px-3 lg:block">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#86868b]">Workspace</p>
      </div>
      <nav className="space-y-2" aria-label="Primary navigation">
        <button
          aria-label="Conversations"
          onClick={() => onViewChange('chat')}
          className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'chat' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
        >
          <MessageCircle size={19} className={activeView === 'chat' ? 'text-[#0071e3]' : ''} />
          <span className="hidden lg:inline">Conversations</span>
        </button>
        <button
          aria-label="Memory"
          onClick={() => onViewChange('memory')}
          className={`flex h-12 w-full items-center justify-center gap-3 rounded-2xl px-3 text-sm font-medium lg:justify-start ${activeView === 'memory' ? 'bg-[#f5f5f7] text-[#1d1d1f] shadow-sm' : 'text-[#6e6e73] hover:bg-[#f5f5f7] hover:text-[#1d1d1f]'}`}
        >
          <BrainCircuit size={19} className={activeView === 'memory' ? 'text-[#0071e3]' : ''} />
          <span className="hidden lg:inline">Memory</span>
        </button>
      </nav>
      <div className="mt-auto hidden rounded-2xl bg-[#f5f5f7] px-4 py-3 lg:block">
        <p className="text-xs font-medium text-[#1d1d1f]">Local by default</p>
        <p className="mt-0.5 text-[11px] leading-4 text-[#86868b]">Your assistant runs on your machine.</p>
      </div>
    </aside>
  )
}

export default Sidebar
