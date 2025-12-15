import "./globals.css";
import { MeguribiHeader } from "@/components/MeguribiHeader";

export const metadata = {
  title: "MEGRIBI Dashboard",
  description: "Oriental Lounge Monitor / MEGRIBI",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body className="bg-black">
        <MeguribiHeader />
        <div className="min-h-screen text-slate-50">{children}</div>
      </body>
    </html>
  );
}
