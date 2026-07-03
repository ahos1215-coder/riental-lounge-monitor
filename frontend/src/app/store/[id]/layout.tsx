// メタデータ生成は src/app/store/[id]/page.tsx の generateMetadata に一本化した
// (旧: このファイル自体が generateMetadata を持っていたが、page.tsx 側が {} を返す
//  無効slugのケースで非strictフォールバック(getStoreMetaBySlug)のメタが漏れて出てしまう
//  問題があったため撤去。セグメントの children パススルーのみ残す)。
export default function StoreSlugLayout({ children }: { children: React.ReactNode }) {
  return children;
}
