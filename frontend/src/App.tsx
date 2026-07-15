import { useState, useEffect } from 'react'
import ChatWindow from './components/ChatWindow/ChatWindow'
import Sidebar from './components/Sidebar/Sidebar'

function App() {
  const [isSidebarOpen, setSidebarOpen] = useState(true)

  useEffect(() => {
    console.log("AniOS Frontend: App has mounted successfully.");
  }, []);

  return (
    <div className="flex h-screen w-full bg-slate-950 text-white overflow-hidden">
      {isSidebarOpen && <Sidebar onClose={() => setSidebarOpen(false)} />}
      <main className="flex-1 flex flex-col relative bg-slate-950">
        <header className="p-4 border-b border-slate-800 flex justify-between items-center z-10">
          <h1 className="font-bold text-lg tracking-tight">AniOS <span className="text-blue-500">Developer Console</span></h1>
          <button 
            onClick={() => setSidebarOpen(!isSidebarOpen)}
            className="p-2 hover:bg-slate-800 rounded transition-colors border border-slate-800"
          >
            {isSidebarOpen ? 'Hide Sidebar' : 'Show Sidebar'}
          </button>
        </header>
        <ChatWindow />
        <div className="fixed bottom-4 right-4 z-50">
           {/* Placeholder for DeveloperPanel - will be rendered here or in main flow */}
        </div>
      </main>
    </div>
  )
}

export default App