"use client";

type Props = {
  title: string;
  json: unknown;
  visible: boolean;
};

export function DebugSection({ title, json, visible }: Props) {
  if (!visible) return null;

  return (
    <section>
      <h2 className="text-xl font-bold mb-2">
        {title}
      </h2>
      <pre className="bg-slate-900 text-slate-100 p-4 rounded text-xs overflow-x-auto">
        {JSON.stringify(json, null, 2)}
      </pre>
    </section>
  );
}
