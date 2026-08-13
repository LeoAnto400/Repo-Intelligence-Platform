import { FileCode2 } from 'lucide-react';

interface SourceCitationsProps {
  files: string[];
  retrievedChunks?: number;
}

export function SourceCitations({ files, retrievedChunks }: SourceCitationsProps) {
  if (files.length === 0) return null;

  return (
    <div className="flex max-w-full flex-col gap-1.5 rounded-lg border border-zinc-800/80 bg-zinc-950/40 px-3 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        Sources{typeof retrievedChunks === 'number' ? ` · ${retrievedChunks} chunks retrieved` : ''}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {files.map((file) => (
          <span
            key={file}
            title={file}
            className="inline-flex items-center gap-1 rounded-md border border-zinc-800 bg-zinc-900/70 px-2 py-1 text-[11px] text-zinc-300"
          >
            <FileCode2 className="h-3 w-3 shrink-0 text-emerald-400" />
            <span className="max-w-[220px] truncate">{file}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
