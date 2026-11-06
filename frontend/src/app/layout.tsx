import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "CryptoLens AI · Market intelligence",
  description:
    "Source-grounded cryptocurrency research and historical risk analytics",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
