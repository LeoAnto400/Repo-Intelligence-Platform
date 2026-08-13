'use client';

import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';

const components: Components = {
  code({ className, children, ...rest }) {
    const match = /language-(\w+)/.exec(className ?? '');
    const text = String(children).replace(/\n$/, '');
    const isInline = !match && !text.includes('\n');

    if (isInline) {
      return (
        <code className="rounded bg-zinc-800 px-1.5 py-0.5 text-[0.85em] text-indigo-300" {...rest}>
          {children}
        </code>
      );
    }

    return (
      <SyntaxHighlighter
        style={oneDark}
        language={match?.[1] ?? 'text'}
        PreTag="div"
        customStyle={{ margin: '0.25rem 0', borderRadius: '0.5rem', fontSize: '0.8rem' }}
      >
        {text}
      </SyntaxHighlighter>
    );
  },
  a({ children, ...rest }) {
    return (
      <a {...rest} target="_blank" rel="noopener noreferrer" className="text-indigo-400 underline hover:text-indigo-300">
        {children}
      </a>
    );
  },
  p({ children }) {
    return <p className="mb-2 leading-6 last:mb-0">{children}</p>;
  },
  ul({ children }) {
    return <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>;
  },
};

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="text-sm leading-6">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
