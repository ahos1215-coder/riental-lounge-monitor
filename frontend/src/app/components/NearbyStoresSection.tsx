type NearbyStoreCard = {
  id: string;
  name: string;
  distance: string;
  hours: string;
  crowd: string;
};

type Props = {
  stores: NearbyStoreCard[];
  onMore?: () => void;
};

export function NearbyStoresSection({ stores, onMore }: Props) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4 shadow-lg">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-sm text-slate-400">近くのお店</p>
          <p className="text-lg font-semibold text-white">徒歩圏内の候補</p>
        </div>
      </div>

      <div className="space-y-3">
        {stores.map((s) => (
          <div
            key={s.id}
            className="rounded border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100"
          >
            <div className="flex items-center justify-between">
              <p className="font-semibold">{s.name}</p>
              <span className="text-xs text-slate-400">{s.distance}</span>
            </div>
            <p className="text-xs text-slate-400">営業時間: {s.hours}</p>
            <p className="text-xs text-slate-300">混み具合: {s.crowd}</p>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={onMore}
        className="mt-4 w-full rounded border border-slate-700 bg-slate-900 py-2 text-sm text-slate-200 hover:border-slate-500"
      >
        もっと見る +6
      </button>
    </div>
  );
}
