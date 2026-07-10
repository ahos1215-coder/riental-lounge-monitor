import {
  DEFAULT_STORE,
  buildStoreFullName,
  getStoreMetaBySlug,
} from "@/app/config/stores";

export const FALLBACK_LAST_STORE = {
  name: buildStoreFullName(getStoreMetaBySlug(DEFAULT_STORE)),
  slug: getStoreMetaBySlug(DEFAULT_STORE).slug,
};

export function getAreaLabelFromSlug(slug: string): string {
  return getStoreMetaBySlug(slug || DEFAULT_STORE).areaLabel || "エリア未設定";
}
