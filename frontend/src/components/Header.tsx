'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Sun, Moon } from 'lucide-react';
import { useTheme } from 'next-themes';
import { Logo } from '@/components/Logo';
import { Button } from '@/components/ui';

export function HeaderActions() {
  const { resolvedTheme, setTheme } = useTheme();
  return <div className="flex items-center gap-2"><button onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')} className="relative grid h-9 w-9 place-items-center rounded-xl text-muted-foreground hover:bg-muted" aria-label="切换主题"><Sun className="h-4 w-4 scale-100 dark:scale-0"/><Moon className="absolute h-4 w-4 scale-0 dark:scale-100"/></button><Link href="/login" className="hidden text-sm font-medium text-muted-foreground hover:text-foreground sm:block">登录</Link><Button size="sm" onClick={() => { window.location.href = '/register'; }}>免费试用</Button></div>;
}

export function Header() {
  const pathname = usePathname();
  if (['/dashboard', '/jobs', '/reports', '/report', '/history', '/settings'].some((prefix) => pathname.startsWith(prefix))) return null;
  return (
    <header className="sticky top-0 z-40 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8"><Logo/><nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex"><Link href="/#templates" className="hover:text-foreground">分析模板</Link><Link href="/#evidence" className="hover:text-foreground">Evidence 机制</Link><Link href="/examples" className="hover:text-foreground">示例报告</Link></nav><HeaderActions/></div>
    </header>
  );
}
