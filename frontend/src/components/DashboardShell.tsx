'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  MessageSquare,
  GitCommit,
  GitPullRequest,
  CircleAlert,
  FolderOpen,
  Menu,
  X,
  PanelLeftClose,
  PanelLeft,
  Github,
  Search,
  Sparkles
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

interface DashboardShellProps {
  children: React.ReactNode;
}

interface NavItem {
  name: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string | number;
  href?: string;
}

import { useRepoStore } from '@/features/repo-metadata/store/useRepoStore';

export default function DashboardShell({ children }: DashboardShellProps) {
  const repository = useRepoStore((state) => state.repository);
  const fetchContext = useRepoStore((state) => state.fetchContext);
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  // Bootstraps active-repository state once per app load, regardless of which
  // route is entered first (deep-linking to /chat must see it too).
  useEffect(() => {
    void fetchContext();
  }, [fetchContext]);
  const [activeItem, setActiveItem] = useState('Overview');

  if (!repository) {
    return (
      <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-indigo-500/30 selection:text-indigo-200 flex flex-col justify-between">
        {/* Standalone Landing Top Header */}
        <header className="h-16 border-b border-zinc-900/60 bg-zinc-950/80 backdrop-blur-md sticky top-0 z-50 flex items-center justify-between px-6 md:px-12">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 shadow-lg shadow-indigo-600/20 text-white font-bold text-sm">
              <Sparkles className="h-5 w-5 text-indigo-100" />
            </div>
            <span className="font-semibold text-base tracking-tight bg-gradient-to-r from-zinc-100 to-zinc-400 bg-clip-text text-transparent">
              GitHub Assistant Platform
            </span>
          </div>
          <div className="flex items-center gap-4">
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-zinc-400 hover:text-zinc-100 transition-colors text-sm font-medium flex items-center gap-2"
            >
              <Github className="h-4.5 w-4.5" />
              <span className="hidden sm:inline">GitHub</span>
            </a>
            <Button size="sm" variant="outline" className="border-zinc-800 text-zinc-300 hover:bg-zinc-900 hover:text-zinc-100 text-xs">
              Documentation
            </Button>
          </div>
        </header>

        {/* Main Content Area (Landing Page) */}
        <main className="flex-1">
          {children}
        </main>

        {/* Footer */}
        <footer className="border-t border-zinc-900/60 bg-zinc-950 p-6 text-center text-xs text-zinc-650">
          © 2026 GitHub Assistant Platform. Powered by FastAPI, ChromaDB, and Gemini. All rights reserved.
        </footer>
      </div>
    );
  }

  const navItems: NavItem[] = [
    { name: 'Overview', icon: LayoutDashboard, href: '/' },
    { name: 'Chat', icon: MessageSquare, badge: 'AI', href: '/chat' },
    { name: 'Commits', icon: GitCommit, href: '/commits' },
    { name: 'Pull Requests', icon: GitPullRequest, badge: 2 },
    { name: 'Issues', icon: CircleAlert },
    { name: 'File Explorer', icon: FolderOpen },
  ];

  return (
    <div className="flex min-h-screen bg-zinc-950 text-zinc-100 font-sans antialiased selection:bg-indigo-500/30 selection:text-indigo-200">
      
      {/* Mobile Drawer Overlay */}
      <AnimatePresence>
        {isMobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsMobileOpen(false)}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 lg:hidden"
          />
        )}
      </AnimatePresence>

      {/* Sidebar Component */}
      <motion.aside
        animate={{ width: isCollapsed ? 72 : 260 }}
        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
        className={cn(
          "fixed inset-y-0 left-0 bg-zinc-900/60 border-r border-zinc-800/50 backdrop-blur-xl z-50 flex flex-col justify-between overflow-hidden",
          "lg:sticky lg:inset-y-0",
          isMobileOpen ? "translate-x-0 w-[260px]" : "-translate-x-full lg:translate-x-0"
        )}
      >
        {/* Sidebar Header */}
        <div className="flex flex-col">
          <div className="h-14 px-4 flex items-center justify-between border-b border-zinc-800/40">
            <div className="flex items-center gap-3 overflow-hidden">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 shadow-lg shadow-indigo-600/20 text-white font-bold text-sm">
                <Sparkles className="h-4 w-4 text-indigo-100" />
              </div>
              {!isCollapsed && (
                <motion.span
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="font-semibold text-sm tracking-tight bg-gradient-to-r from-zinc-100 to-zinc-400 bg-clip-text text-transparent whitespace-nowrap"
                >
                  GitHub Assistant Platform
                </motion.span>
              )}
            </div>
            
            {/* Collapse toggle (desktop only) */}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="hidden lg:flex h-8 w-8 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60"
            >
              {isCollapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
            </Button>

            {/* Mobile close button */}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsMobileOpen(false)}
              className="lg:hidden h-8 w-8 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/60"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>

          {/* Navigation Items */}
          <nav className="p-3 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = item.href ? pathname === item.href : activeItem === item.name;

              const itemClassName = cn(
                "w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 relative group",
                isActive
                  ? "text-zinc-50 bg-zinc-800/80 border border-zinc-700/30 shadow-sm"
                  : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/30 border border-transparent"
              );

              const itemContent = (
                <>
                  <div className="flex items-center gap-3">
                    <Icon className={cn("h-4.5 w-4.5 shrink-0", isActive ? "text-indigo-400" : "text-zinc-400 group-hover:text-zinc-200")} />
                    {!isCollapsed && (
                      <motion.span
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        className="whitespace-nowrap"
                      >
                        {item.name}
                      </motion.span>
                    )}
                  </div>

                  {/* Badges */}
                  {!isCollapsed && item.badge && (
                    <span className={cn(
                      "px-1.5 py-0.5 rounded text-[10px] font-semibold leading-none",
                      item.badge === 'AI'
                        ? "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20"
                        : "bg-zinc-800 text-zinc-400"
                    )}>
                      {item.badge}
                    </span>
                  )}

                  {/* Tooltip on Collapsed Sidebar */}
                  {isCollapsed && (
                    <div className="absolute left-16 px-2.5 py-1.5 bg-zinc-900 border border-zinc-800 rounded-md text-xs font-semibold text-zinc-100 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none shadow-xl z-50 whitespace-nowrap">
                      {item.name}
                    </div>
                  )}
                </>
              );

              if (item.href) {
                return (
                  <Link
                    key={item.name}
                    href={item.href}
                    onClick={() => setIsMobileOpen(false)}
                    className={itemClassName}
                  >
                    {itemContent}
                  </Link>
                );
              }

              return (
                <button
                  key={item.name}
                  onClick={() => {
                    setActiveItem(item.name);
                    setIsMobileOpen(false);
                  }}
                  className={itemClassName}
                >
                  {itemContent}
                </button>
              );
            })}
          </nav>
        </div>

        {/* Sidebar Footer */}
        <div className="p-3 border-t border-zinc-800/40 space-y-3">
          {/* Active Repo Status Indicator */}
          <div className={cn(
            "flex items-center rounded-lg p-2.5 bg-zinc-950/40 border border-zinc-800/30 overflow-hidden",
            isCollapsed ? "justify-center" : "gap-3"
          )}>
            <div className="relative flex h-2 w-2 shrink-0">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </div>
            {!isCollapsed && (
              <div className="flex flex-col text-left overflow-hidden min-w-0">
                <span className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider">Ingested Repository</span>
                <span className="text-xs font-medium text-zinc-300 truncate">{repository}</span>
              </div>
            )}
          </div>
        </div>
      </motion.aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        
        {/* Fixed Top Navigation Bar */}
        <header className="h-14 sticky top-0 z-30 border-b border-zinc-800/40 bg-zinc-950/80 backdrop-blur-md px-6 flex items-center justify-between gap-4">
          
          {/* Left: Mobile Toggle & Breadcrumb */}
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsMobileOpen(true)}
              className="lg:hidden h-8 w-8 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900"
            >
              <Menu className="h-5 w-5" />
            </Button>

            <div className="flex items-center gap-2">
              <div className="relative flex h-2 w-2 shrink-0">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </div>
              <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Ingested Repository</span>
              <span className="text-sm font-medium text-zinc-100">{repository}</span>
            </div>
          </div>

          {/* Center: Global Search Bar Placeholder */}
          <div className="hidden md:flex relative max-w-sm w-full">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-500" />
            <input
              type="text"
              placeholder="Search code, commits, issues..."
              className="w-full bg-zinc-900/50 border border-zinc-800/80 rounded-lg py-1.5 pl-9 pr-4 text-xs text-zinc-300 placeholder-zinc-500 focus:outline-none focus:border-zinc-700/80 transition-colors"
              readOnly
            />
            <div className="absolute right-2.5 top-2 px-1.5 py-0.5 rounded bg-zinc-800 text-[10px] text-zinc-500 font-mono border border-zinc-700/55 select-none pointer-events-none">
              ⌘K
            </div>
          </div>

          {/* Right: Action Area */}
          <div className="flex items-center gap-2.5">
            {/* GitHub connect status */}
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-zinc-850 hover:border-zinc-800 hover:bg-zinc-900 text-zinc-400 hover:text-zinc-100 transition-colors"
            >
              <Github className="h-4.5 w-4.5" />
            </a>
          </div>
        </header>

        {/* Content View Area */}
        <main className="flex-1 overflow-y-auto min-w-0 bg-zinc-950">
          <div className="p-6 md:p-8 max-w-7xl mx-auto w-full">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
