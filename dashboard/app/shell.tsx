"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { ic: "◈", label: "Command Center", href: "/" },
  { ic: "⬡", label: "Agents", href: "/agents" },
  { ic: "↯", label: "Signals", href: "/signals" },
  { ic: "✦", label: "Execution Logs", href: "/logs" },
  { ic: "🜲", label: "Risk Vault", href: "/risk" },
  { ic: "❖", label: "Market Memory", href: "/memory" },
  { ic: "𝌆", label: "Strategies", href: "" },
  { ic: "⟲", label: "Backtests", href: "" },
  { ic: "⚙", label: "Settings", href: "" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="shell">
      <header className="topbar">
        <img src="/binacci-logo.png" alt="Binacci" width={34} height={34}
             style={{ borderRadius: 8, border: "1px solid var(--border-gold)" }} />
        <div className="wordmark"><span className="b">BINACCI</span><span className="ai">AI</span></div>
      </header>
      <div className="body">
        <nav className="sidebar">
          <div className="nav-label">Navigate</div>
          {NAV.map((n) =>
            n.href ? (
              <Link key={n.label} href={n.href}
                    className={path === n.href ? "nav-item active" : "nav-item"}>
                <span className="ic">{n.ic}</span>{n.label}
              </Link>
            ) : (
              <div key={n.label} className="nav-item">
                <span className="ic">{n.ic}</span>{n.label}
                <span className="soon">soon</span>
              </div>
            )
          )}
        </nav>
        {children}
      </div>
    </div>
  );
}
