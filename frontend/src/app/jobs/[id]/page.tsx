'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
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

  useEffect(() => { load(); const timer = setInterval(load, 2500); return () => clearInterval(timer); }, [load]);
  const cancel = async () => { setJob(await cancelJob(id)); await load(); };
  const retry = async () => { const updated = await retryJob(id); router.replace(`/jobs/${updated.id}`); };

  return <AppShell><div className="mx-auto max-w-3xl">{loading ? <LoadingState label="正在读取任务状态"/> : error ? <ErrorState description={error} action={<Button onClick={load}>重试</Button>}/> : job && <><div className="flex flex-wrap items-start justify-between gap-4"><div><Link href="/history" className="text-sm text-muted-foreground hover:text-foreground">← 返回任务列表</Link><h1 className="mt-3 text-2xl font-bold">{job.query}</h1><div className="mt-3 flex items-center gap-3"><StatusBadge status={job.status}/><span className="text-sm text-muted-foreground">进度 {job.progress}%</span></div></div><div className="flex gap-2">{['pending','running'].includes(job.status) && <Button variant="danger" size="sm" onClick={cancel}>取消任务</Button>}{['failed','cancelled'].includes(job.status) && <Button size="sm" onClick={retry}>重新分析</Button>}</div></div><Card className="mt-7 p-5 sm:p-7"><div className="mb-6 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-gradient-to-r from-indigo-600 to-cyan-500 transition-all" style={{width:`${job.progress}%`}}/></div><JobProgress status={job.status} events={events}/></Card>{job.error_message && <Card className="mt-4 border-red-200 p-5 dark:border-red-900"><h2 className="font-semibold text-red-700 dark:text-red-300">任务未完成</h2><p className="mt-2 text-sm text-muted-foreground">{job.error_message}</p><p className="mt-2 font-mono text-xs text-muted-foreground">{job.error_code}</p></Card>}<p className="mt-5 text-center text-xs text-muted-foreground">可以安全刷新或关闭页面。任务状态由后端 Worker 持久化。</p></>}</div></AppShell>;
}
