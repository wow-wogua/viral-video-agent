import Link from 'next/link';
import { ArrowRight, BarChart3, Check, FileSearch, Link2, Play, SearchCheck, ShieldCheck, Target } from 'lucide-react';
import { Card, LinkButton } from '@/components/ui';

const templates = [
  { title: 'B站赛道分析', template: 'B站赛道爆款分析', description: '样本、内容形态、竞争结构。', kicker: 'Track scan', icon: BarChart3, span: 'md:col-span-2' },
  { title: '竞品账号拆解', template: '竞品账号内容拆解', description: '定位、选题、可复用策略。', kicker: 'Competitor', icon: Target, span: '' },
  { title: '热门标题分析', template: '热门标题结构分析', description: '钩子、信息密度、受众承诺。', kicker: 'Headline', icon: SearchCheck, span: '' },
  { title: '选题方向分析', template: '选题方向分析', description: '筛选值得验证的方向。', kicker: 'Topic map', icon: FileSearch, span: '' },
  { title: '脚本深度分析', template: '内容脚本深度分析', description: '开头、口播、内容结构。', kicker: 'Transcript', icon: Link2, span: 'md:col-span-2 lg:col-span-1' },
];

const evidenceFeatures = [
  ['稳定引用', '每条证据都有 evidence_id。'],
  ['结论门禁', '无引用，不发布。'],
  ['来源可回看', '一键回到真实来源。'],
  ['边界透明', '不把个例当规律。'],
];

export default function HomePage() {
  return (
    <main>
      <section className="editorial-grid relative overflow-hidden border-b">
        <div className="absolute right-0 top-0 h-full w-[38%] bg-primary/5 [clip-path:polygon(18%_0,100%_0,100%_100%,0_100%)]" aria-hidden="true" />
        <div className="speed-lines absolute -right-24 top-10 h-72 w-72 rotate-12 opacity-50" aria-hidden="true" />
        <div className="mx-auto max-w-7xl px-4 pb-16 pt-8 sm:px-6 sm:pb-20 lg:px-8 lg:pb-24">
          <div className="motion-enter flex flex-wrap items-center justify-between gap-3 border-y border-foreground/20 py-2 font-mono text-[10px] font-semibold uppercase tracking-[.14em] text-muted-foreground">
            <span>Viral Video Agent / Research Desk</span><span className="text-primary">Bilibili only · Public samples</span><span>Evidence-led reports</span>
          </div>

          <div className="grid gap-10 pt-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(25rem,.8fr)] lg:items-center lg:gap-16 lg:pt-16">
            <div className="motion-enter min-w-0">
              <div className="inline-flex items-center gap-2 rounded-full border border-success/30 bg-success/10 px-3 py-1.5 text-xs font-semibold text-success"><ShieldCheck className="h-4 w-4" aria-hidden="true" />当前仅支持 B 站公开样本</div>
              <p className="eyebrow mt-7">Content intelligence / 01</p>
              <h1 className="title-balance mt-4 max-w-4xl text-5xl font-black leading-[.98] tracking-[-.065em] sm:text-6xl lg:text-7xl">真实样本进场，<br /><span className="relative text-primary">可验证结论出片<span className="absolute -bottom-2 left-0 h-2 w-full bg-accent/70" aria-hidden="true" /></span></h1>
              <p className="mt-7 max-w-xl text-pretty text-lg leading-8 text-muted-foreground">输入赛道或竞品，生成带来源的 B 站内容分析报告。</p>
              <div className="mt-8 flex flex-wrap gap-3"><LinkButton href="/register" size="lg">开始分析<ArrowRight className="h-4 w-4" aria-hidden="true" /></LinkButton><LinkButton href="/examples" size="lg" variant="secondary">看示例</LinkButton></div>
              <div className="mt-8 grid max-w-2xl grid-cols-3 border-y py-4">
                {[['真实来源', '可回看'], ['结构结论', '可验证'], ['B站限定', '边界清晰']].map(([value, label], index) => <div key={label} className="border-r px-3 first:pl-0 last:border-r-0 last:pr-0"><p className="font-mono text-xs font-semibold text-foreground sm:text-sm">{value}</p><p className="mt-1 text-[11px] text-muted-foreground">0{index + 1} / {label}</p></div>)}
              </div>
            </div>

            <Card className="motion-enter-delay relative overflow-hidden bg-surface-elevated p-0 shadow-float">
              <div className="flex items-center justify-between gap-4 bg-secondary px-5 py-4 text-secondary-foreground">
                <div><p className="font-mono text-[10px] uppercase tracking-[.16em] text-primary">Report pipeline</p><p className="mt-1 text-sm font-bold">AI 编程赛道分析</p></div>
                <span className="rounded-full border border-success/40 bg-success/20 px-2.5 py-1 font-mono text-[10px] font-semibold text-success">Evidence 通过</span>
              </div>
              <div className="relative p-5 sm:p-6">
                <svg className="pointer-events-none absolute right-2 top-2 h-40 w-44 text-primary/20" viewBox="0 0 180 150" fill="none" aria-hidden="true"><path d="M20 115 68 72l34 18 48-62" stroke="currentColor" strokeWidth="2"/><circle cx="20" cy="115" r="6" fill="currentColor"/><circle cx="68" cy="72" r="6" fill="currentColor"/><circle cx="102" cy="90" r="6" fill="currentColor"/><circle cx="150" cy="28" r="6" fill="currentColor"/></svg>
                <div className="relative space-y-0">
                  {['采集 8 条样本', '检索 5 条依据', '验证 12 条结论', '生成报告'].map((item, index) => (
                    <div key={item} className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 border-b py-3.5 last:border-b-0">
                      <span className="grid h-9 w-9 place-items-center rounded-full border border-success/40 bg-success/10 text-success"><Check className="h-4 w-4" aria-hidden="true" /></span>
                      <span className="text-sm font-semibold">{item}</span><span className="editorial-number">0{index + 1}</span>
                    </div>
                  ))}
                </div>
                <div className="relative mt-5 border-l-4 border-primary bg-primary/10 p-4 text-sm leading-6">高播放标题常见“结果前置 + 明确受众”。<Link href="#evidence" className="ml-2 font-mono text-xs font-semibold text-primary underline underline-offset-4">[ev_bili_01]</Link></div>
              </div>
            </Card>
          </div>
        </div>
      </section>

      <section id="templates" className="mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-20 lg:px-8 lg:py-24">
        <div className="border-b pb-8">
          <p className="eyebrow">Analysis formats / 02</p>
          <h2 className="title-balance mt-3 text-4xl font-black tracking-[-.045em] sm:text-5xl">选择分析方式</h2>
          <p className="mt-3 max-w-xl text-pretty text-base leading-7 text-muted-foreground">选一个模板，也可直接输入需求。</p>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {templates.map(({ title, template, description, kicker, icon: Icon, span }, index) => (
            <Link key={title} href={`/jobs/new?template=${encodeURIComponent(template)}`} className={`group block rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background ${span}`}>
              <Card className="relative h-full min-h-48 overflow-hidden p-5 transition-[border-color,box-shadow] group-hover:border-primary/40 group-hover:shadow-float sm:p-6">
                <div className="absolute right-0 top-0 h-16 w-16 border-b border-l bg-muted/60 [clip-path:polygon(100%_0,100%_100%,0_0)]" aria-hidden="true" />
                <div className="flex items-center justify-between"><span className="grid h-11 w-11 place-items-center rounded-xl border bg-primary/10 text-primary"><Icon className="h-5 w-5" aria-hidden="true" /></span><span className="editorial-number">0{index + 1}</span></div>
                <p className="eyebrow mt-6">{kicker}</p><h3 className="mt-2 text-xl font-bold tracking-[-.025em]">{title}</h3><p className="mt-2 max-w-md text-pretty text-sm leading-6 text-muted-foreground">{description}</p>
                <div className="mt-5 flex items-center gap-2 text-xs font-semibold text-primary opacity-70 transition-opacity group-hover:opacity-100">开始分析<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></div>
              </Card>
            </Link>
          ))}
        </div>
      </section>

      <section id="evidence" className="relative overflow-hidden bg-secondary text-secondary-foreground">
        <div className="halftone absolute -left-24 -top-24 h-80 w-80 opacity-20" aria-hidden="true" />
        <div className="speed-lines absolute bottom-0 right-0 h-72 w-[42%] opacity-20" aria-hidden="true" />
        <div className="relative mx-auto grid max-w-7xl gap-12 px-4 py-16 sm:px-6 sm:py-20 lg:grid-cols-[.8fr_1.2fr] lg:px-8 lg:py-24">
          <div>
            <p className="eyebrow">Evidence system / 03</p><h2 className="title-balance mt-4 text-4xl font-black tracking-[-.045em] sm:text-5xl">结论有来源。</h2>
            <p className="mt-6 max-w-lg text-pretty leading-8 text-secondary-foreground/68">保存真实 URL 和关键字段；证据不足时明确降级。</p>
            <div className="mt-8 inline-flex items-center gap-3 border-y border-white/20 py-3 text-sm"><span className="grid h-10 w-10 place-items-center rounded-full bg-primary text-primary-foreground"><Play className="h-4 w-4 fill-current" aria-hidden="true" /></span><span><strong className="block">Evidence first</strong><span className="text-xs text-secondary-foreground/60">从可回看的样本开始判断</span></span></div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {evidenceFeatures.map(([title, description], index) => (
              <div key={title} className="relative min-h-44 border border-white/20 bg-white/[.045] p-5 backdrop-blur-sm sm:p-6">
                <span className="absolute right-5 top-5 font-mono text-[10px] text-secondary-foreground/40">NODE / 0{index + 1}</span>
                <span className="mb-7 block h-3 w-3 rounded-full border-4 border-secondary bg-primary ring-1 ring-primary" aria-hidden="true" />
                <h3 className="text-lg font-bold">{title}</h3><p className="mt-2 text-sm leading-6 text-secondary-foreground/62">{description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 sm:py-20 lg:px-8 lg:py-24">
        <div className="grid gap-10 lg:grid-cols-[.7fr_1.3fr]">
          <div><p className="eyebrow">Workflow / 04</p><h2 className="title-balance mt-3 text-4xl font-black tracking-[-.045em]">四步完成。</h2></div>
          <ol className="grid border-t sm:grid-cols-2">
            {['输入需求', '采集样本', '验证结论', '生成报告'].map((item, index) => <li key={item} className="grid min-h-28 grid-cols-[3rem_1fr] gap-3 border-b p-4 sm:border-r sm:p-5"><span className="font-mono text-2xl font-black text-primary">0{index + 1}</span><span className="text-sm font-semibold leading-6">{item}</span></li>)}
          </ol>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pb-16 sm:px-6 sm:pb-20 lg:px-8 lg:pb-24">
        <div className="relative overflow-hidden bg-primary p-7 text-primary-foreground shadow-float sm:p-9 lg:flex lg:items-center lg:justify-between lg:gap-10">
          <div className="halftone absolute -right-8 -top-12 h-44 w-44 opacity-20" aria-hidden="true" />
          <div className="relative"><p className="font-mono text-[10px] font-semibold uppercase tracking-[.16em]">Open beta / Bilibili only</p><h2 className="title-balance mt-2 text-3xl font-black tracking-[-.04em]">开始一个真实需求。</h2><p className="mt-2 text-sm text-primary-foreground/80">仅支持 B 站公开样本。</p></div>
          <LinkButton href="/register" variant="secondary" size="lg" className="relative mt-6 border-white/50 bg-white text-secondary hover:bg-white/90 lg:mt-0">开始分析<ArrowRight className="h-4 w-4" aria-hidden="true" /></LinkButton>
        </div>
      </section>
    </main>
  );
}
