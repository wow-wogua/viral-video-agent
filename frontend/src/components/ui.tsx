'use client';

import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type SelectHTMLAttributes } from 'react';
import { AlertCircle, Inbox, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; size?: 'sm' | 'md' | 'lg' }>(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => (
    <button ref={ref} className={cn('inline-flex items-center justify-center gap-2 rounded-xl font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 disabled:pointer-events-none disabled:opacity-50', variant === 'primary' && 'bg-indigo-600 text-white hover:bg-indigo-700', variant === 'secondary' && 'border bg-card text-foreground hover:bg-muted', variant === 'ghost' && 'text-muted-foreground hover:bg-muted hover:text-foreground', variant === 'danger' && 'bg-red-600 text-white hover:bg-red-700', size === 'sm' && 'h-9 px-3 text-sm', size === 'md' && 'h-10 px-4 text-sm', size === 'lg' && 'h-12 px-5 text-base', className)} {...props} />
  ),
);
Button.displayName = 'Button';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn('h-11 w-full rounded-xl border bg-background px-3 text-sm outline-none transition placeholder:text-muted-foreground focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20', className)} {...props} />
));
Input.displayName = 'Input';

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...props }, ref) => (
  <select ref={ref} className={cn('h-11 w-full rounded-xl border bg-background px-3 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20', className)} {...props} />
));
Select.displayName = 'Select';

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-2xl border bg-card shadow-sm', className)} {...props} />;
}

const statusStyles: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  running: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-200',
  completed: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200',
  partial: 'bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-200',
  failed: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-200',
  cancelled: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
};
const statusLabels: Record<string, string> = { pending: '排队中', running: '分析中', completed: '已完成', partial: '部分完成', failed: '失败', cancelled: '已取消' };

export function StatusBadge({ status }: { status: string }) {
  return <span className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-medium', statusStyles[status] ?? statusStyles.pending)}>{statusLabels[status] ?? status}</span>;
}

export function EmptyState({ title = '暂无内容', description, action }: { title?: string; description?: string; action?: React.ReactNode }) {
  return <div className="flex min-h-52 flex-col items-center justify-center px-6 text-center"><Inbox className="mb-3 h-8 w-8 text-muted-foreground"/><h3 className="font-medium">{title}</h3>{description && <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>}{action && <div className="mt-5">{action}</div>}</div>;
}

export function ErrorState({ title = '加载失败', description = '请稍后重试。', action }: { title?: string; description?: string; action?: React.ReactNode }) {
  return <div className="flex min-h-52 flex-col items-center justify-center px-6 text-center"><AlertCircle className="mb-3 h-8 w-8 text-red-500"/><h3 className="font-medium">{title}</h3><p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>{action && <div className="mt-5">{action}</div>}</div>;
}

export function Skeleton({ className }: { className?: string }) { return <div className={cn('animate-pulse rounded-lg bg-muted', className)} />; }
export function LoadingState({ label = '正在加载' }: { label?: string }) { return <div className="flex min-h-52 items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin"/>{label}</div>; }

export function Modal({ open, title, children, onClose }: { open: boolean; title: string; children: React.ReactNode; onClose: () => void }) {
  if (!open) return null;
  return <div className="fixed inset-0 z-[70] grid place-items-center bg-slate-950/50 p-4" role="dialog" aria-modal="true" aria-label={title} onMouseDown={onClose}><Card className="w-full max-w-lg p-6" onMouseDown={(event) => event.stopPropagation()}><div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">{title}</h2><Button variant="ghost" size="sm" onClick={onClose}>关闭</Button></div>{children}</Card></div>;
}

export function Toast({ message }: { message: string }) { return <div className="fixed bottom-5 right-5 z-[80] rounded-xl bg-slate-950 px-4 py-3 text-sm text-white shadow-xl dark:bg-white dark:text-slate-950">{message}</div>; }
