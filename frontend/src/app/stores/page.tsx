import { Suspense } from "react";
import StoresListClient from "./stores-list-client";

function StoresFallback() {
  return (
    <div className="flex min-h-[60vh] w-full items-center justify-center bg-[#050505] font-display text-sm text-white/50">
      読み込み中…
    </div>
  );
}

export default function StoresPage() {
  return (
    <Suspense fallback={<StoresFallback />}>
      <StoresListClient />
    </Suspense>
  );
}
