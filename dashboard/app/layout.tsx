import type { Metadata } from "next";
import "./globals.css";
import Shell from "./shell";

export const metadata: Metadata = {
  title: "Binacci AI — Command Center",
  description:
    "Mythic intelligence meets autonomous trading infrastructure. Deterministic strategy, agentic execution, full audit trails.",
  icons: { icon: "/favicon.png", apple: "/apple-icon.png" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
