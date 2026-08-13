'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { AlertTriangle, Home, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center px-4 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400">
        <AlertTriangle className="h-6 w-6" />
      </div>
      <h1 className="mt-6 text-xl font-semibold text-zinc-100">Something went wrong</h1>
      <p className="mt-2 max-w-md text-sm text-zinc-400">
        {error.message || 'An unexpected error occurred while rendering this page.'}
      </p>
      <div className="mt-6 flex items-center gap-3">
        <Button onClick={() => reset()} className="gap-1.5">
          <RotateCcw className="h-3.5 w-3.5" />
          Try again
        </Button>
        <Button variant="outline" render={<Link href="/" />} className="gap-1.5">
          <Home className="h-3.5 w-3.5" />
          Go home
        </Button>
      </div>
    </div>
  );
}
