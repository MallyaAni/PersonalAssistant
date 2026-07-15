import React,{ useState } from 'react'
import { Activity, Zap, Terminal } from 'lucide-react'

const DeveloperPanel: React.FC = () => {
  const [isOpen, setIsOpen] = useState(true)

  // Mock data for development purposes
  const [metrics] = useState({
    traceId: "tr_9b1d8f2a3c4e5f6g7h8i",
    latency: "1.42s",
    nodesExecuted: ["init_state", "retrieval_semantic", "assistant_node"],
    status: "success"
  })

  return (
    <div className="absolute top-0 right-0 m-4 p-4 bg-slate-900 border border-slate-700 rounded-lg shadow-xl w-80">
      <div className="flex justify-between items-center mb%3 border-b border-slate-800 pb-2">
        <h3 className="font-bold flex items-center gap-2">
          <Terminal size={16} /> Dev Metrics
        </h3>
        <button onClick={() => setIsOpen(!isOpen)} className="text-gray-400 hover:text-white">
          {isOpen ? '-' : '+'}
        </button>
      </div>

      {isOpen && (
        <div className="space-y-3 text-sm font-mono">
          <div className="flex justify-between gap-2">
            <span className="text-gray-400">Trace ID:</span>
            <span className="text-blue-400">{metrics.traceId}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-gray-400">Latency:</span>
            <span className="text-green-400">{metrics.latency}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="text-gray-400">Nodes:</span>
            <span className="text-orange-400">{metrics.nodesExecuted.join(' $\rightarrow$ ')}</span>
          </div>
          <div className="pt-2 border-t border-slate-800">
            <p className="text-gray-500 mb-1 text-[10px] uppercase tracking-widest font-bold">Status</p>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              <span className="text-green-500">{metrics.status}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default DeveloperPanel