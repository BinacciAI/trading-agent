import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Binacci Agent",
  description: "Reaction-based autonomous trading agent — live console",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
