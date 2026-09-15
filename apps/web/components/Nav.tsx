"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/people", label: "People" },
  { href: "/places", label: "Places" },
  { href: "/photos", label: "Photos" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="nav">
      {links.map(({ href, label }) => {
        const isCurrent = pathname === href;
        return (
          <Link key={href} href={href} aria-current={isCurrent ? "page" : undefined}>
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
