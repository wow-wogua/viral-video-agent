import Image from 'next/image';
import Link from 'next/link';
import { cn } from '@/lib/utils';

export function Logo({ compact = false, className }: { compact?: boolean; className?: string }) {
  return (
    <Link href="/" className={cn('inline-flex items-center gap-2.5', className)} aria-label="爆款视频分析首页">
      <Image src="/logo-mark.svg" alt="" width={36} height={36} priority />
      {!compact && <span className="whitespace-nowrap text-base font-semibold tracking-tight">爆款视频分析</span>}
    </Link>
  );
}
