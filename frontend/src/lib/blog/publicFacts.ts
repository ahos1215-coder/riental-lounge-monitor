import "server-only";
import fs from "node:fs";
import path from "node:path";

export type PublicFacts = {
  facts_id: string;
  store?: { id: string; label?: string };
  range?: { from: string; to: string; timezone?: string };
  level?: "easy" | "normal" | "pro";
  insight?: {
    peak_time?: string;
    avoid_time?: string;
    crowd_label?: string;
  };
  series_min?: Array<{ t: string; total?: number; men?: number; women?: number }>;
  quality_flags?: { missing?: boolean; notes?: string[] };
};

function getFactsPath(factsId: string): string {
  // frontend/content/facts/public/<facts_id>.json
  return path.join(process.cwd(), "content", "facts", "public", `${factsId}.json`);
}

export function readPublicFacts(factsId: string): PublicFacts | null {
  if (!factsId) return null;
  const p = getFactsPath(factsId);
  if (!fs.existsSync(p)) return null;
  try {
    const raw = fs.readFileSync(p, "utf8").replace(/^\uFEFF/, "");
    return JSON.parse(raw) as PublicFacts;
  } catch {
    return null;
  }
}
