'use client';

import { Brain, Cpu, Layers, Sparkles } from 'lucide-react';
import { useRepoStore } from '@/features/repo-metadata/store/useRepoStore';
import { RepositoryDashboard } from '@/features/repo-metadata/components/RepositoryDashboard';
import { RepositoryPicker } from '@/features/repo-metadata/components/RepositoryPicker';
import { IngestPanel } from '@/features/ingestion/components/IngestPanel';

interface FeatureCardProps {
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  glowColor: string;
}

function FeatureCard({ title, description, icon: Icon, glowColor }: FeatureCardProps) {
  return (
    <div className="relative group rounded-xl border border-zinc-800/60 bg-zinc-900/20 p-6 backdrop-blur-md transition-all duration-300 hover:border-zinc-700/80 hover:bg-zinc-900/40 text-left overflow-hidden">
      {/* Dynamic Hover Glow */}
      <div className={`absolute -right-10 -top-10 h-32 w-32 rounded-full opacity-0 group-hover:opacity-10 transition-opacity duration-500 blur-2xl pointer-events-none ${glowColor}`} />

      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-900 border border-zinc-800 text-zinc-400 group-hover:text-indigo-400 group-hover:border-indigo-500/30 transition-all duration-300">
        <Icon className="h-5 w-5" />
      </div>
      <h3 className="mt-4 font-semibold text-zinc-100 group-hover:text-white transition-colors text-sm">{title}</h3>
      <p className="mt-2 text-xs text-zinc-400 leading-relaxed">{description}</p>
    </div>
  );
}

export default function Home() {
  const repository = useRepoStore((state) => state.repository);

  if (repository) {
    return <RepositoryDashboard />;
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col justify-center px-4 relative overflow-hidden">

      {/* Background Ornaments */}
      <div className="absolute top-[-10%] left-[20%] h-[500px] w-[500px] rounded-full bg-indigo-500/5 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[10%] right-[10%] h-[400px] w-[400px] rounded-full bg-emerald-500/5 blur-[100px] pointer-events-none" />

      {/* Main Landing View */}
      <div className="max-w-4xl mx-auto w-full text-center py-16 md:py-24 space-y-16">

        {/* Hero Section */}
        <div className="space-y-6 max-w-2xl mx-auto">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Sparkles className="h-3.5 w-3.5" />
            <span>Agentic Codebase Search</span>
          </div>

          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight bg-gradient-to-b from-zinc-50 to-zinc-400 bg-clip-text text-transparent leading-[1.15]">
            Understand Any GitHub Codebase in Seconds
          </h1>

          <p className="text-sm md:text-base text-zinc-400 leading-relaxed">
            Ingest and index public/private repositories. Chat with specialized AI agents powered by FastAPI, ChromaDB, and Gemini to map structural imports, locate features, and write adjustments.
          </p>
        </div>

        {/* Previously Ingested Repositories */}
        <RepositoryPicker />

        {/* Ingest a New Repository */}
        <IngestPanel />

        {/* Feature Cards Grid */}
        <div className="grid gap-6 md:grid-cols-3 pt-6">
          <FeatureCard
            title="RetrievalAgent"
            description="Performs semantic parsing on vector code chunks using ChromaDB collections to resolve dependencies and import scopes."
            icon={Layers}
            glowColor="bg-indigo-500"
          />
          <FeatureCard
            title="AnalysisAgent"
            description="Leverages Gemini Pro to parse structures, explain logic paths, synthesise context, and propose optimizations."
            icon={Brain}
            glowColor="bg-emerald-500"
          />
          <FeatureCard
            title="Multi-Agent Orchestrator"
            description="Coordinates state flow using LangGraph execution loops to route prompts, retrieve context, and generate chat output."
            icon={Cpu}
            glowColor="bg-pink-500"
          />
        </div>

      </div>
    </div>
  );
}
