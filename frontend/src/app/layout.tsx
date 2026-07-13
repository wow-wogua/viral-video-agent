import type { Metadata } from 'next';
import { ThemeProvider } from '@/components/ThemeProvider';
import { Header } from '@/components/Header';
import './globals.css';

export const metadata: Metadata = {
  title: '爆款视频分析',
  description: '用真实B站样本生成可验证的内容分析报告',
  icons: { icon: '/favicon.svg' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans antialiased">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <div className="relative flex min-h-screen flex-col">
            <Header />
            <main className="flex-1">{children}</main>
          </div>
        </ThemeProvider>
      </body>
    </html>
  );
}
