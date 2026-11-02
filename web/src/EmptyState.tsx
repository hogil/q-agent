import { Search } from 'lucide-react';

export default function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="empty-state">
      <Search size={25} strokeWidth={1.3} />
      <h3>{title}</h3>
      <p>{detail}</p>
    </div>
  );
}
