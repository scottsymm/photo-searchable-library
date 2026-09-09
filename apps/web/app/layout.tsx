import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Pics | Searchable memories",
  description: "A private, searchable photo library",
};

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="shell">
      <header className="topbar">
        <Link className="brand" href="/">pics.</Link>
        <nav className="nav">
          <Link href="/people">People</Link>
          <Link href="/places">Places</Link>
          <Link href="/settings">Settings</Link>
        </nav>
      </header>
      {children}
    </div>
  );
}
