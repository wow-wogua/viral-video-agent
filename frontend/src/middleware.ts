import { NextRequest, NextResponse } from 'next/server';

const protectedPrefixes = ['/dashboard', '/jobs', '/reports', '/report', '/history', '/settings'];

export function middleware(request: NextRequest) {
  const requiresAuth = protectedPrefixes.some((prefix) => request.nextUrl.pathname.startsWith(prefix));
  if (!requiresAuth || request.cookies.has('viral_video_session')) return NextResponse.next();
  const loginUrl = new URL('/login', request.url);
  loginUrl.searchParams.set('next', `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.redirect(loginUrl);
}

export const config = { matcher: ['/dashboard/:path*', '/jobs/:path*', '/reports/:path*', '/report/:path*', '/history/:path*', '/settings/:path*'] };
