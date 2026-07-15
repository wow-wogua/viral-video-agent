'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { ArrowLeft, RotateCcw, Square } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { JobProgress } from '@/components/product';
import { Button, Card, ErrorState, LoadingState, StatusBadge } from '@/components/ui';
import { cancelJob, getJob, getJobEvents, readableError, retryJob, type Job, type JobEvent } from '@/lib/api';

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const [jobData, eventData] = await Promise.all([getJob(id), getJobEvents(id)]);
      setJob(jobData);
      setEvents(eventData.items);
      setError('');
      if (jobData.report_id && ['completed', 'partial'].includes(jobData.status)) router.replace(`/reports/${jobData.report_id}`);
    } catch (err) {
      setError(readableError(err));
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  }, [load]);

  const cancel = async () => { setJob(await cancelJob(id)); await load(); };
  const retry = async () => { const updated = await retryJob(id); router.replace(`/jobs/${updated.id}`); };

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl">
        {loading ? <LoadingState label="正在读取任务状态" /> : error ? <ErrorState description={error} action={<Button onClick={load}>重新读取</Button>} /> : job && (
          <>
            <Link href="/history" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><ArrowLeft className="h-4 w-4" aria-hidden="true" />返回任务列表</Link>
            <div className="mt-4 grid gap-5 border-b pb-7 sm:grid-cols-[1fr_auto] sm:items-start">
              <div className="min-w-0"><p className="eyebrow">Live job / {job.id.slice(0, 6)}</p><h1 className="break-content title-balance mt-2 text-2xl font-black tracking-[-.035em] sm:text-3xl">{job.query}</h1><div className="mt-4 flex flex-wrap items-center gap-3"><StatusBadge status={job.status} /><span className="font-mono text-xs tabular-nums text-muted-foreground">进度 {job.progress}%</span><span className="text-xs text-muted-foreground">B站 · {job.analysis_mode === 'deep' ? '内容深度分析' : '标准分析'}</span></div></div>
              <div className="flex gap-2">{['pending', 'running'].includes(job.status) && <Button variant="danger" size="sm" onClick={cancel}><Square className="h-3.5 w-3.5" aria-hidden="true" />取消任务</Button>}{['failed', 'cancelled'].includes(job.status) && <Button size="sm" onClick={retry}><RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />重新分析</Button>}</div>
            </div>

            <Card className="mt-7 overflow-hidden p-0">
              <div className="bg-secondary px-5 py-5 text-secondary-foreground sm:px-7"><div className="flex items-center justify-between gap-4"><div><p className="font-mono text-[10px] uppercase tracking-[.16em] text-primary">Execution timeline</p><h2 className="mt-1 font-bold">任务执行进度</h2></div><span className="font-mono text-2xl font-black tabular-nums">{job.progress}%</span></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-white/10" role="progressbar" aria-label="任务执行进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={job.progress}><div className="h-full rounded-full bg-gradient-to-r from-primary to-accent transition-[width]" style={{ width: `${job.progress}%` }} /></div></div>
              <div className="p-5 sm:p-7"><JobProgress status={job.status} events={events} /></div>
            </Card>

            {job.error_message && <Card className="mt-4 border-destructive/30 p-5"><p className="eyebrow text-destructive">Job interrupted</p><h2 className="mt-1 font-bold text-destructive">任务未完成</h2><p className="break-content mt-2 text-sm leading-6 text-muted-foreground">{job.error_message}</p><p className="mt-3 font-mono text-xs text-muted-foreground">{job.error_code}</p></Card>}
            <p className="mt-5 text-center text-xs leading-5 text-muted-foreground">可以安全刷新或关闭页面。任务状态由后端 Worker 持久化，页面每 2.5 秒读取一次进度。</p>
          </>
        )}
      </div>
    </AppShell>
  );
}
