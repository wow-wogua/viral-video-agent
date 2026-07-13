'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from 'next-themes';
import { BarChart3, FilePlus2, Files, Gauge, Menu, Moon, Settings, Sun, UserRound, X } from 'lucide-react';
import { useState } from 'react';
import { Logo } from '@/components/Logo';
import { cn } from '@/lib/utils';

const items = [
  { href: '/dashboard', label: 'Dashboard', icon: Gauge },
  { href: '/jobs/new', label: '新建分析', icon: FilePlus2 },
  { href: '/history', label: '任务与报告', icon: Files },
  { href: '/examples', label: '示例报告', icon: BarChart3 },
  { href: '/settings', label: '设置与用量', icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  const navigation = <>{items.map(({ href, label, icon: Icon }) => <Link key={href} href={href} onClick={() => setOpen(false)} className={cn('flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium', pathname === href || pathname.startsWith(`${href}/`) ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-200' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}><Icon className="h-4 w-4"/>{label}</Link>)}</>;
  const accountActions = <div className="flex items-center gap-2"><button onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')} className="relative grid h-9 w-9 place-items-center rounded-xl text-muted-foreground hover:bg-muted" aria-label="切换主题"><Sun className="h-4 w-4 scale-100 dark:scale-0"/><Moon className="absolute h-4 w-4 scale-0 dark:scale-100"/></button><Link href="/settings" className="grid h-9 w-9 place-items-center rounded-xl text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="账号设置"><UserRound className="h-4 w-4"/></Link></div>;

  return <div className="min-h-screen bg-background"><aside className="fixed inset-y-0 left-0 z-50 hidden w-64 border-r bg-card p-5 print:hidden lg:block"><Logo/><nav className="mt-8 space-y-1">{navigation}</nav><div className="absolute bottom-5 left-5 right-5 rounded-xl border bg-background p-3 text-xs text-muted-foreground"><strong className="mb-1 block text-foreground">当前能力边界</strong>仅支持公开可访问的 B 站样本分析。</div></aside>{open && <div className="fixed inset-0 z-50 bg-slate-950/40 lg:hidden" onClick={() => setOpen(false)}><aside className="h-full w-72 bg-card p-5" onClick={(event) => event.stopPropagation()}><div className="flex items-center justify-between"><Logo/><button onClick={() => setOpen(false)} aria-label="关闭菜单"><X className="h-5 w-5"/></button></div><nav className="mt-8 space-y-1">{navigation}</nav></aside></div>}<div className="lg:pl-64"><header className="sticky top-0 z-40 flex h-16 items-center justify-between border-b bg-background/90 px-4 backdrop-blur print:hidden sm:px-6 lg:px-8"><button className="rounded-lg p-2 lg:hidden" onClick={() => setOpen(true)} aria-label="打开菜单"><Menu className="h-5 w-5"/></button><div className="hidden text-sm text-muted-foreground sm:block">可验证的 B 站内容研究工作台</div>{accountActions}</header><main className="mx-auto max-w-7xl px-4 py-7 sm:px-6 lg:px-8">{children}</main></div></div>;
}
