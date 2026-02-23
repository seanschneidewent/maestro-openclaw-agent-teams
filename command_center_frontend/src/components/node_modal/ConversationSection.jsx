import React from 'react'
import { DrawerCard } from './shared'

export default function ConversationSection({
  loading,
  error,
  conversation,
  sendEnabled,
  sending,
  draft,
  setDraft,
  onSend,
}) {
  const messages = Array.isArray(conversation?.messages) ? conversation.messages : []
  return (
    <DrawerCard title="Live Conversation" className="xl:col-span-2">
      {loading && messages.length === 0 && <div className="text-xs text-slate-500 mb-2">Loading conversation...</div>}
      {error && <div className="text-xs text-rose-300 mb-2">{error}</div>}
      <div className="max-h-72 overflow-auto space-y-2 pr-1">
        {messages.length === 0 ? (
          <div className="text-xs text-slate-500">No conversation yet.</div>
        ) : (
          messages.map((msg) => (
            <div
              key={msg.id || `${msg.timestamp}-${msg.role}`}
              className={`border p-2 text-xs ${msg.role === 'assistant' ? 'border-[#00e5ff]/30 bg-[#00e5ff]/5' : 'border-white/10 bg-black/40'}`}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="uppercase tracking-widest text-[10px] text-slate-500">{msg.role}</span>
                <span className="font-mono text-[10px] text-slate-500">{msg.timestamp || ''}</span>
              </div>
              <div className="text-slate-200 whitespace-pre-wrap">{msg.text}</div>
            </div>
          ))
        )}
      </div>
      <form
        className="mt-3"
        onSubmit={(event) => {
          event.preventDefault()
          const text = String(draft || '').trim()
          if (!text || !sendEnabled || sending) return
          onSend(text)
        }}
      >
        <textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          rows={3}
          disabled={!sendEnabled || sending}
          placeholder={sendEnabled ? 'Send a manual message to this project maestro...' : 'Conversation is read-only for this node.'}
          className="w-full bg-black/40 border border-white/15 px-2 py-2 text-xs text-slate-200 disabled:opacity-60"
        />
        <div className="mt-2 flex justify-between items-center">
          {!sendEnabled && (
            <span className="text-[10px] uppercase tracking-widest text-amber-400">
              Send disabled for this node
            </span>
          )}
          <button
            type="submit"
            disabled={!sendEnabled || sending || !String(draft || '').trim()}
            className="ml-auto border border-white/20 text-slate-300 px-2 py-1 text-[10px] uppercase tracking-widest font-mono hover:border-[#00e5ff] hover:text-[#00e5ff] disabled:opacity-50"
          >
            {sending ? 'Sending...' : 'Send'}
          </button>
        </div>
      </form>
    </DrawerCard>
  )
}
