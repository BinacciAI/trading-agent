"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { ic: "◈", label: "Command Center", href: "/" },
  { ic: "🏁", label: "Competition", href: "/competition" },
  { ic: "⬡", label: "Agents", href: "/agents" },
  { ic: "↯", label: "Signals", href: "/signals" },
  { ic: "✦", label: "Execution Logs", href: "/logs" },
  { ic: "🜲", label: "Risk Vault", href: "/risk" },
  { ic: "❖", label: "Market Memory", href: "/memory" },
  { ic: "𝌆", label: "Strategies", href: "/strategies" },
  { ic: "⟲", label: "Backtests", href: "/backtests" },
  { ic: "⚙", label: "Settings", href: "/settings" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="shell">
      <header className="topbar">
        <img src="/binacci-logo.png" alt="Binacci" width={32} height={32}
             style={{ borderRadius: 8, border: "1px solid var(--border-gold)" }} />
        <div className="wordmark"><span className="b">BINACCI</span><span className="ai">AI</span></div>
        <span className="topbar-tag">BNB · CMC · TRUST WALLET</span>
      </header>
      <div className="body">
        <nav className="sidebar">
          <div className="nav-label">Navigate</div>
          {NAV.map((n) => (
            <Link key={n.label} href={n.href}
                  className={path === n.href ? "nav-item active" : "nav-item"}>
              <span className="ic">{n.ic}</span>{n.label}
            </Link>
          ))}
          <div className="nav-foot">v0.2 · live on BSC</div>
        </nav>
        {children}
      </div>
    </div>
  );
}
