'use client';

import { useParams } from 'next/navigation';
import { Eye, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { EvidenceCard, ReportClaim } from '@/components/product';
import { Card, ErrorState, LoadingState, StatusBadge } from '@/components/ui';
import { getSharedReport, readableError, type Report } from '@/lib/api';

export default function SharedReportPage() {
  const { token } = useParams<{ token: string }>();
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');

  useEffect(() => { getSharedReport(token).then(setReport).catch((err) => setError(readableError(err))); }, [token]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-10 sm:px-6 sm:py-12 lg:px-8">
      {error ? <ErrorState title="分享链接不可用" description={error} /> : !report ? <LoadingState label="正在加载只读报告" /> : (
        <>
          <div className="grid gap-6 border-b pb-7 lg:grid-cols-[1fr_auto] lg:items-end">
            <div className="min-w-0"><div className="flex flex-wrap items-center gap-3"><StatusBadge status={report.status} /><span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-muted-foreground"><Eye className="h-3.5 w-3.5" aria-hidden="true" />只读分享</span></div><p className="eyebrow mt-4">Shared report / public</p><h1 className="break-content title-balance mt-2 text-3xl font-black tracking-[-.045em] sm:text-4xl">{report.title}</h1><p className="mt-3 max-w-3xl text-pretty text-sm leading-6 text-muted-foreground">此页面仅展示报告、结构化结论与来源证据，不包含用户信息、成本详情或内部执行日志。</p></div>
            <div className="inline-flex items-center gap-2 text-xs font-semibold text-success"><ShieldCheck className="h-4 w-4" aria-hidden="true" />脱敏只读响应</div>
          </div>

          <div className="mt-7 grid gap-7 xl:grid-cols-[minmax(0,1fr)_17rem]">
            <div className="min-w-0 space-y-9">
              <Card className="print-card overflow-hidden p-0"><div className="bg-secondary px-6 py-5 text-secondary-foreground"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-primary">Viral Video Agent</p><p className="mt-1 text-sm font-semibold">B 站内容分析 · 公开只读版本</p></div><article className="report-prose p-5 sm:p-8"><ReactMarkdown remarkPlugins={[remarkGfm]}>{report.content}</ReactMarkdown></article></Card>
              <section aria-labelledby="shared-claims"><div className="mb-4 flex items-end justify-between gap-4 border-b pb-3"><div><p className="eyebrow">Claims / 02</p><h2 id="shared-claims" className="mt-1 text-2xl font-black tracking-[-.03em]">结构化结论</h2></div><span className="editorial-number">{report.structured_claims.length} ITEMS</span></div><div className="space-y-3">{report.structured_claims.map((claim, index) => <ReportClaim key={index} claim={claim} />)}</div></section>
              <section aria-labelledby="shared-evidence"><div className="mb-4 flex items-end justify-between gap-4 border-b pb-3"><div><p className="eyebrow">Sources / 03</p><h2 id="shared-evidence" className="mt-1 text-2xl font-black tracking-[-.03em]">Evidence 来源</h2></div><span className="editorial-number">{report.evidence.length} ITEMS</span></div><div className="space-y-3">{report.evidence.map((item) => <EvidenceCard key={item.evidence_id} evidence={item} />)}</div></section>
            </div>
            <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start"><Card className="p-5"><p className="eyebrow">Public boundary</p><h2 className="mt-2 font-bold">分享页不包含</h2><ul className="mt-4 space-y-3 text-sm text-muted-foreground"><li>用户邮箱与身份信息</li><li>Token、成本与用量</li><li>Agent 内部执行轨迹</li><li>Worker 错误详情</li></ul></Card><Card className="p-5"><p className="eyebrow">Platform</p><p className="mt-3 text-sm leading-6 text-muted-foreground">本报告只围绕公开可访问的 B 站样本，不代表全平台或行业总体。</p></Card></aside>
          </div>
        </>
      )}
    </main>
  );
}
