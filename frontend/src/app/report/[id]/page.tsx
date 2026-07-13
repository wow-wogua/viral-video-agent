import { redirect } from 'next/navigation';
export default function LegacyReportPage({ params }: { params: { id: string } }) { redirect(`/reports/${params.id}`); }
