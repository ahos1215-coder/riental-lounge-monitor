import { useEffect, useState } from "react";

import type { StoreId } from "../../components/MeguribiDashboardPreview";
import { getSecondVenueMapLinks, type SecondVenueMapLink } from "../config/secondVenueMapLinks";

export type SecondVenue = SecondVenueMapLink;

type SecondVenuesState = {
  loading: boolean;
  error: string | null;
  data: SecondVenue[];
};

export function useSecondVenues(storeId: StoreId): SecondVenuesState {
  const [state, setState] = useState<SecondVenuesState>({
    loading: true,
    error: null,
    data: [],
  });

  useEffect(() => {
    let cancelled = false;

    function run() {
      // ネットワークアクセスは行わず、ローカル設定からリンクを生成する
      try {
        const links = getSecondVenueMapLinks(storeId);
        if (!cancelled) {
          setState({ loading: false, error: null, data: links });
        }
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        // eslint-disable-next-line no-console
        console.error("useSecondVenues.error", detail);
        if (!cancelled) {
          setState({ loading: false, error: detail, data: [] });
        }
      }
    }

    run();

    return () => {
      cancelled = true;
    };
  }, [storeId]);

  return state;
}
