import "./globals.css";

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
      <body>{children}</body>
    </html>
  );
}
