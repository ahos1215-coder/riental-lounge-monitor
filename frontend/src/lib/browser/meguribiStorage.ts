/**
 * ブラウザ専用（localStorage）。SSR では呼ばないこと。
 * マイページ・店舗履歴・お気に入り（端末内のみ、未ログイン）。
 */

export const LAST_STORE_KEY = "meguribi:lastStoreSlug";
export const STORE_HISTORY_KEY = "meguribi:storeHistorySlugs";
export const FAVORITE_STORES_KEY = "meguribi:favoriteStoreSlugs";

const MAX_HISTORY = 12;
const MAX_FAVORITES = 30;

function normalizeSlug(slug: string): string {
  return slug.trim().toLowerCase();
}

function readJsonStringArray(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const p = JSON.parse(raw) as unknown;
    if (!Array.isArray(p)) return [];
    return p.filter((x): x is string => typeof x === "string").map((s) => normalizeSlug(s)).filter(Boolean);
  } catch {
    return [];
  }
}

/** 最終閲覧店舗＋履歴の先頭に追加（重複は除く） */
export function recordStoreVisit(slug: string): void {
  if (typeof window === "undefined") return;
  const s = normalizeSlug(slug);
  if (!s) return;
  try {
    window.localStorage.setItem(LAST_STORE_KEY, s);
    const list = readJsonStringArray(window.localStorage.getItem(STORE_HISTORY_KEY)).filter((x) => x !== s);
    list.unshift(s);
    window.localStorage.setItem(STORE_HISTORY_KEY, JSON.stringify(list.slice(0, MAX_HISTORY)));
  } catch {
    // ignore quota / private mode
  }
}

export function getStoreHistorySlugs(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return readJsonStringArray(window.localStorage.getItem(STORE_HISTORY_KEY));
  } catch {
    return [];
  }
}

export function getFavoriteStoreSlugs(): string[] {
  if (typeof window === "undefined") return [];
  try {
    return readJsonStringArray(window.localStorage.getItem(FAVORITE_STORES_KEY)).slice(0, MAX_FAVORITES);
  } catch {
    return [];
  }
}

export function isFavoriteStore(slug: string): boolean {
  const s = normalizeSlug(slug);
  if (!s) return false;
  return getFavoriteStoreSlugs().includes(s);
}

/** お気に入りに追加。既にあれば何もしない。上限時は false。 */
export function addFavoriteStore(slug: string): boolean {
  if (typeof window === "undefined") return false;
  const s = normalizeSlug(slug);
  if (!s) return false;
  try {
    const cur = getFavoriteStoreSlugs();
    if (cur.includes(s)) return true;
    if (cur.length >= MAX_FAVORITES) return false;
    cur.push(s);
    window.localStorage.setItem(FAVORITE_STORES_KEY, JSON.stringify(cur));
    return true;
  } catch {
    return false;
  }
}

export function removeFavoriteStore(slug: string): void {
  if (typeof window === "undefined") return;
  const s = normalizeSlug(slug);
  if (!s) return;
  try {
    const cur = getFavoriteStoreSlugs().filter((x) => x !== s);
    window.localStorage.setItem(FAVORITE_STORES_KEY, JSON.stringify(cur));
  } catch {
    // ignore
  }
}

export function toggleFavoriteStore(slug: string): boolean {
  if (isFavoriteStore(slug)) {
    removeFavoriteStore(slug);
    return false;
  }
  return addFavoriteStore(slug);
}

export function clearStoreHistory(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORE_HISTORY_KEY);
  } catch {
    // ignore
  }
}

export function clearFavoriteStores(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(FAVORITE_STORES_KEY);
  } catch {
    // ignore
  }
}
