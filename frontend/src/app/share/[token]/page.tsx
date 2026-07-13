'use client';

import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { EvidenceCard, ReportClaim } from '@/components/product';
import { Card, ErrorState, LoadingState, StatusBadge } from '@/components/ui';
import { getSharedReport, readableError, type Report } from '@/lib/api';

export default function SharedReportPage() { const { token } = useParams<{token:string}>(); const [report, setReport] = useState<Report | null>(null); const [error, setError] = useState(''); useEffect(() => { getSharedReport(token).then(setReport).catch((err) => setError(readableError(err))); }, [token]); return <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">{error ? <ErrorState title="分享链接不可用" description={error}/> : !report ? <LoadingState/> : <><div className="mb-6"><div className="flex items-center gap-3"><StatusBadge status={report.status}/><span className="text-xs text-muted-foreground">只读分享</span></div><h1 className="mt-3 text-2xl font-bold">{report.title}</h1><p className="mt-2 text-sm text-muted-foreground">此页面仅展示报告、结构化结论与来源证据，不包含用户信息或内部执行日志。</p></div><Card className="p-5 sm:p-8"><article className="report-prose prose prose-slate max-w-none dark:prose-invert"><ReactMarkdown remarkPlugins={[remarkGfm]}>{report.content}</ReactMarkdown></article></Card><section className="mt-8"><h2 className="mb-3 text-lg font-semibold">结构化结论</h2><div className="space-y-3">{report.structured_claims.map((claim, index) => <ReportClaim key={index} claim={claim}/>)}</div></section><section className="mt-8"><h2 className="mb-3 text-lg font-semibold">Evidence 来源</h2><div className="space-y-3">{report.evidence.map((item) => <EvidenceCard key={item.evidence_id} evidence={item}/>)}</div></section></>}</main>; }
