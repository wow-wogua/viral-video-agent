'use client';

import { useRouter } from 'next/navigation';
import { ChevronRight, Search } from 'lucide-react';
import { useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { useAnalyzeStore } from '@/stores/analyzeStore';
import { getHistory } from '@/lib/api';

const platformFilters = [
  { id: 'all', label: '全部' },
  { id: 'bilibili', label: 'Bilibili' },
  { id: 'douyin', label: '抖音' },
];

export default function HistoryPage() {
  const router = useRouter();
  const { records } = useAnalyzeStore();
  const [search, setSearch] = useState('');
  const [platform, setPlatform] = useState('all');
  const [remoteRecords, setRemoteRecords] = useState<any[]>([]);

  useEffect(() => {
    getHistory().then((data) => {
      if (data.source === 'redis' && data.records.length > 0) {
        setRemoteRecords(data.records);
      }
    }).catch(() => {});
  }, []);

  // 合并远程记录和本地记录，远程优先
  const allRecords = remoteRecords.length > 0
    ? [...remoteRecords, ...records.filter((r) => !remoteRecords.some((rr: any) => rr.id === r.id))]
    : records;

  const filtered = allRecords.filter((r) => {
    const matchSearch = !search || r.title.includes(search);
    const matchPlatform = platform === 'all' || r.platform === platform;
    return matchSearch && matchPlatform;
  });

  return (
    <div className="mx-auto max-w-5xl px-8 pt-10 pb-24">
      <h1 className="mb-8 text-2xl font-bold">历史报告</h1>

      <div className="card-3d mb-6 flex items-center gap-4 rounded-3xl border bg-card p-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索报告..."
            className="w-full rounded-2xl border bg-transparent py-2 pl-10 pr-4 text-sm outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="flex gap-2">
          {platformFilters.map((f) => (
            <button
              key={f.id}
              onClick={() => setPlatform(f.id)}
              className={cn(
                'rounded-2xl px-4 py-1.5 text-sm font-medium transition-colors',
                platform === f.id
                  ? 'bg-primary/20 text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent'
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="card-3d rounded-3xl border bg-card">
        {filtered.length === 0 ? (
          <div className="px-6 py-16 text-center text-base text-muted-foreground">
            暂无报告
          </div>
        ) : (
          filtered.map((r, i) => (
            <button
              key={r.id}
              onClick={() => router.push(`/report/${r.id}`)}
              className={cn(
                'flex w-full items-center justify-between px-6 py-4 text-left transition-colors hover:bg-accent',
                i !== filtered.length - 1 && 'border-b'
              )}
            >
              <div className="flex items-center gap-4">
                <span className="text-sm text-muted-foreground">{r.date}</span>
                <span className="rounded-2xl bg-primary/20 px-3 py-1 text-xs text-primary-foreground">
                  {r.platform}
                </span>
                <span className="text-base">{r.title}</span>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    'text-sm',
                    r.status === 'completed' ? 'text-primary' : 'text-muted-foreground'
                  )}
                >
                  {r.status === 'completed' ? '已完成' : '分析中'}
                </span>
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
