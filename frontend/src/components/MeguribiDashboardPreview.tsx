"use client";

import type { ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import { useStorePreviewData, type StoreSnapshot } from "../app/hooks/useStorePreviewData";
import {
  DEFAULT_STORE,
  getStoreMetaBySlugOrDefault,
} from "../app/config/stores";

/**
 * PreviewMainSection（Recharts本体を含むダッシュボード）は ssr:false の dynamic import。
 * これはバンドルサイズ的には正しいが、素の next/dynamic だと「このコンポーネントが実際に
 * レンダーされる（= hydration 完了後）まで import() が発火しない」ため、4G回線では
 * hydration完了 → チャンクのダウンロード開始 → 描画、という直列待ちになり数秒のロスが出る
 * （実測: numbers visible 4.1s → chart visible 7.4s、ギャップ3.3s＝このチャンクDL）。
 *
 * 当初は useEffect 内で呼ぶ案を検討したが、CPUスロットル下の実測で「useEffect の初回発火
 * 自体が hydration 完了まで(4x throttleで約1.3s)ブロックされる」ことが分かり、それでは
 * 結局チャンクDL開始が hydration 後にずれ込んでしまい効果が出なかった（before/after で
 * gap がほぼ変わらなかった）。
 *
 * そこでモジュール評価時（このファイルのトップレベル、コンポーネント関数の外）に
 * import() を1回発火させる。このファイル自体は StorePageClient → MeguribiDashboardPreview
 * という通常の静的 import チェーンでメインバンドルの一部として早期に読み込まれるため、
 * スクリプトの評価は React の hydration/commit を待たずに走る。webpack/Next の
 * モジュールキャッシュは import() の Promise をモジュール単位でメモ化するため、
 * 実際に <PreviewMainSection /> がマウントされる時点ではチャンクのDLが既に完了、または
 * 同時並行で進行中になり、直列だった「hydration → DL → 描画」を「hydration と並行DL →
 * 描画」に変えられる。
 *
 * 注意: dynamic() に渡す関数自体とは別に、ここで直接 import() を呼んでいるのは、
 * bundler が dynamic() 呼び出しをその場で静的解析してチャンク分割の目印にするため、
 * loader 関数を条件なく即時実行してもチャンク分割自体は変わらない
 * （下記ビルド出力の chunk 分離を参照）ことをローカルビルドで確認済み。
 */
const previewMainSectionLoader = () => import("./PreviewMainSection");

// モジュール評価時に即時発火（コンポーネントのレンダー/エフェクトを待たない）。
void previewMainSectionLoader();

const PreviewMainSection = dynamic(previewMainSectionLoader, {
  ssr: false,
  loading: () => (
    <div className="h-80 w-full animate-pulse rounded-2xl bg-slate-800/60" />
  ),
});

type MeguribiDashboardPreviewProps = {
  /** 店舗名横にお気に入りボタンなど */
  headerActions?: ReactNode;
  /** サーバーで取得済みの初回スナップショット（page.tsx 由来）。無ければ通常の CSR。 */
  initialSnapshot?: StoreSnapshot | null;
  /**
   * URLパス（/store/[id]）由来の店舗 slug。渡された場合、?store= クエリより優先する。
   *
   * 経緯: このコンポーネント単体では従来 `searchParams.get("store") ?? DEFAULT_STORE` だけで
   * slug を決めていたが、/store/[id] への直接アクセス直後は StorePageInner の URL 同期
   * useEffect がまだ走っておらず `?store=` が付いていない瞬間があり、その一瞬だけ
   * DEFAULT_STORE 相当にフォールバックしてしまっていた（元コードでは毎回 loading:true から
   * 始まるため無害だったが、initialSnapshot による即時描画は「最初のレンダーで正しい店舗の
   * slug と一致するか」に依存するため、この一瞬のズレが致命的になる）。
   * StorePageInner 自身は既に slugFromPath を searchParams より優先しているため、同じ
   * 優先順位をここでも揃える。
   */
  pathSlug?: string;
};

export default function MeguribiDashboardPreview({ headerActions, initialSnapshot, pathSlug }: MeguribiDashboardPreviewProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const slug = pathSlug || searchParams.get("store") || DEFAULT_STORE;
  const meta = getStoreMetaBySlugOrDefault(slug);

  const {
    snapshot,
    loading,
    error,
    rangeMode,
    setRangeMode,
    customDate,
    setCustomDate,
    selectedBaseDate,
  } = useStorePreviewData(meta.slug, initialSnapshot);

  // 2026-09-06 計測レビュー追跡: ここは URLSearchParams に store キーを毎回入れてクエリを
  // 組み立てていたため、遷移先が必ず `/store/<slug>?store=<slug>`（非正規URL）になっていた。
  // 2026-08-26 の「内部リンクの ?store= 全除去」はリテラル `?store=` の文字列検索で直したので、
  // このプログラム的な組み立てだけが取り残された（番犬テスト internalLinks.test.ts も
  // リテラル形しか見ていなかったため素通りした）。/store/[id] は path slug を優先して query を
  // 読まず、canonical も `/store/<slug>` なので、クエリを付ける理由が無い。
  //
  // 他のクエリを引き継がないのは意図的: utm_* / gclid を内部遷移に持ち回すと、pathname が
  // 変わる＝GoogleAnalytics.tsx が PV を送る際の page_location に混入し、GA4 上で流入元が
  // 再帰属されてしまう。`?dev=` は syncDevOptOutFromQuery が既に localStorage へ保存済みなので
  // 引き継ぎ不要。結果として他の内部 /store/ リンク（StoreCard 等）と同じ素の形に揃う。
  //
  // 注意: 現在 PreviewMainSection は onSelectStore を props 型に持つだけで呼んでいない
  // （店舗切替スイッチャーのUIが無い）ため、この関数は今は発火しない＝今回の変更は挙動不変。
  // 将来スイッチャーを復活させた時に非正規URLが一緒に復活しないよう、URL側を先に直しておく。
  const handleSelectStore = (nextSlug: string) => {
    if (!nextSlug || nextSlug === meta.slug) return;
    router.push(`/store/${encodeURIComponent(nextSlug)}`, { scroll: false });
  };

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 text-slate-50">
      <PreviewMainSection
        storeSlug={meta.slug}
        snapshot={snapshot}
        onSelectStore={handleSelectStore}
        loading={loading}
        error={error}
        rangeMode={rangeMode}
        onChangeRangeMode={setRangeMode}
        customDate={customDate}
        onChangeCustomDate={setCustomDate}
        selectedBaseDate={selectedBaseDate}
        storeHeaderActions={headerActions}
      />
    </main>
  );
}
