import React from 'react'
import { MessageSquare, History, Settings, Info } from 'lucide-react'

interface SidebarProps {
  onClose: () => void
}

const Sidebar: React.FC<SidebarProps> = ({ onClose }) => {
  return (
    <div className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col p-4 space-y-6">
      <h2 className="text-xl font% bold text-white mb-4">AniOS Dev</h2>
      <nav className="space-y-2">
        <div className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded cursor-pointer transition-colors">
          <MessageSquare size={18} />
          <span>Conversations</span>
        </div>
        <div className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded cursor-pointer transition-colors">
          <History size={18} />
          <span>Memory Logs</span>
        </div>
        <div className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded cursor-pointer transition-colors">
          <Settings size={18} />
          <span>Configuration</span>
        </div>
        <div className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded cursor-pointer transition-colors">
          <Info size={18} />
          <span>About_Docs</span>
        </div>
      </nav>
    </div>
  )
}

export default Sidebar