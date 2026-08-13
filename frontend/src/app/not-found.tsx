import Link from 'next/link';
import { FileQuestion, Home } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function NotFound() {
  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center px-4 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-zinc-900 border border-zinc-800 text-zinc-400">
        <FileQuestion className="h-6 w-6" />
      </div>
      <h1 className="mt-6 text-xl font-semibold text-zinc-100">Page not found</h1>
      <p className="mt-2 max-w-md text-sm text-zinc-400">
        The page you&apos;re looking for doesn&apos;t exist or may have been moved.
      </p>
      <Button render={<Link href="/" />} className="mt-6 gap-1.5">
        <Home className="h-3.5 w-3.5" />
        Go home
      </Button>
    </div>
  );
}
