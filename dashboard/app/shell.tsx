"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/* On-brand line-icon set — single 1.6px stroke, currentColor so each icon
   inherits the nav state (muted → primary on hover → gold when active). The
   wing-spiral mark stays the page's one signature; the nav stays quiet. */
const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
function Icon({ name }: { name: string }) {
  const paths: Record<string, React.ReactNode> = {
    command: (<><circle cx="12" cy="12" r="8" {...P} /><circle cx="12" cy="12" r="2.5" {...P} /><path d="M12 1.5V5M12 19v3.5M1.5 12H5M19 12h3.5" {...P} /></>),
    competition: (<><path d="M6 21V4" {...P} /><path d="M6 4h11l-2.2 3.5L17 11H6" {...P} /></>),
    agents: (<><path d="M12 3l7.5 4.3v8.4L12 20l-7.5-4.3V7.3z" {...P} /><circle cx="12" cy="12" r="2.4" {...P} /></>),
    signals: (<path d="M2 13h4l2.5-7 4 14 2.5-7H22" {...P} />),
    logs: (<><circle cx="5" cy="7" r="1" fill="currentColor" /><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="5" cy="17" r="1" fill="currentColor" /><path d="M9 7h11M9 12h11M9 17h11" {...P} /></>),
    risk: (<><path d="M12 3l7 2.8v5.4c0 4.2-3 7-7 8.8-4-1.8-7-4.6-7-8.8V5.8z" {...P} /><path d="M9 12l2 2 4-4.5" {...P} /></>),
    memory: (<><ellipse cx="12" cy="6" rx="7" ry="3" {...P} /><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" {...P} /><path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" {...P} /></>),
    strategies: (<><circle cx="6" cy="6" r="2.2" {...P} /><circle cx="6" cy="18" r="2.2" {...P} /><circle cx="18" cy="12" r="2.2" {...P} /><path d="M8 7l8 4M8 17l8-4" {...P} /></>),
    backtests: (<><path d="M3.5 12a8.5 8.5 0 1 0 2.7-6.2L3 8" {...P} /><path d="M3 3.5V8h4.5" {...P} /><path d="M12 8v4.2l3 1.8" {...P} /></>),
    settings: (<><path d="M4 7h9M17 7h3M4 17h3M11 17h9" {...P} /><circle cx="15" cy="7" r="2.2" {...P} /><circle cx="7" cy="17" r="2.2" {...P} /></>),
    console: (<><rect x="3" y="3" width="18" height="18" rx="3" {...P} /><path d="M8 8v8M12 11v5M16 8v3" {...P} /><circle cx="8" cy="6.5" r="1.3" fill="currentColor" /><circle cx="12" cy="9.5" r="1.3" fill="currentColor" /><circle cx="16" cy="6.5" r="1.3" fill="currentColor" /></>),
  };
  return (
    <svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}

type NavItem = { section: string } | { ic: string; label: string; href: string };
const NAV: NavItem[] = [
  { section: "Monitor" },
  { ic: "command", label: "Terminal", href: "/" },
  { ic: "strategies", label: "Swarm", href: "/strategies" },
  { section: "Operate" },
  { ic: "settings", label: "Controls", href: "/settings" },
  { ic: "risk", label: "Go Live", href: "/golive" },
]

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className="shell">
      <header className="topbar">
        <img src="/binacci-logo.png" alt="Binacci" width={30} height={30} className="brandmark" />
        <div className="wordmark"><span className="b">BINACCI</span><span className="ai">AI</span></div>
      </header>
      <div className="body">
        <nav className="sidebar">
          {NAV.map((n, i) =>
            "section" in n ? (
              <div key={i} className="nav-label">{n.section}</div>
            ) : (
              <Link key={n.href} href={n.href}
                    className={path === n.href ? "nav-item active" : "nav-item"}>
                <span className="ic"><Icon name={n.ic} /></span>{n.label}
              </Link>
            )
          )}
          <div className="nav-foot">v0.2 · live on BSC</div>
        </nav>
        {children}
      </div>
    </div>
  );
}
