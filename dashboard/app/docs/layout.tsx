import { DocsNav } from "@/components/DocsNav";

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="container section first">
      <div className="docs">
        <DocsNav />
        <div className="docs-body">{children}</div>
      </div>
    </main>
  );
}
