import {
  DEFAULT_STORE,
  buildStoreFullName,
  getStoreMetaBySlugOrDefault,
} from "@/app/config/stores";

export const FALLBACK_LAST_STORE = {
  name: buildStoreFullName(getStoreMetaBySlugOrDefault(DEFAULT_STORE)),
  slug: getStoreMetaBySlugOrDefault(DEFAULT_STORE).slug,
};

export function getAreaLabelFromSlug(slug: string): string {
  return getStoreMetaBySlugOrDefault(slug || DEFAULT_STORE).areaLabel || "エリア未設定";
}
