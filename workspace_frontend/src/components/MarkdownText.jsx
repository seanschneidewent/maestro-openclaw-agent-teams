import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const SIZE_CLASS = {
  xs: 'text-xs',
  sm: 'text-sm',
  tiny: 'text-[11px]',
}

export default function MarkdownText({ content, className = '', size = 'sm' }) {
  const text = String(content || '').trim()
  if (!text) return null

  const sizeClass = SIZE_CLASS[size] || SIZE_CLASS.sm

  return (
    <div className={`${sizeClass} leading-relaxed break-words ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="mb-1.5 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="my-1.5 ml-4 list-disc space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="my-1.5 ml-4 list-decimal space-y-1">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-1.5 border-l-2 border-slate-300 pl-2 text-slate-600">{children}</blockquote>
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-cyan-700 underline underline-offset-2">
              {children}
            </a>
          ),
          code: ({ inline, children }) =>
            inline ? (
              <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.95em] text-slate-700">{children}</code>
            ) : (
              <code className="block whitespace-pre-wrap rounded bg-slate-100 px-2 py-1 text-[0.95em] text-slate-700">
                {children}
              </code>
            ),
          hr: () => <hr className="my-2 border-slate-300" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}
