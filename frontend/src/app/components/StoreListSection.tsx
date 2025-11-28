type StoreListItem = {
  id: string;
  name: string;
  men: number;
  women: number;
  distance: string;
  hours: string;
};

type Props = {
  stores: StoreListItem[];
};

export function StoreListSection({ stores }: Props) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-white">全店舗一覧</h2>
      <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-950 shadow-lg">
        <table className="w-full text-sm text-slate-100">
          <thead className="bg-slate-900 text-xs text-slate-400">
            <tr>
              <th className="px-3 py-2 text-left">店舗名</th>
              <th className="px-3 py-2 text-left">男</th>
              <th className="px-3 py-2 text-left">女</th>
              <th className="px-3 py-2 text-left">距離</th>
              <th className="px-3 py-2 text-left">営業時間</th>
            </tr>
          </thead>
          <tbody>
            {stores.map((s) => (
              <tr key={s.id} className="border-t border-slate-800">
                <td className="px-3 py-2">{s.name}</td>
                <td className="px-3 py-2 text-sky-300">♂ {s.men}</td>
                <td className="px-3 py-2 text-pink-300">♀ {s.women}</td>
                <td className="px-3 py-2 text-slate-300">{s.distance}</td>
                <td className="px-3 py-2 text-slate-300">{s.hours}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
