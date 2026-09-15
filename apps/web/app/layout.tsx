import type { Metadata } from "next";
import Link from "next/link";
import { Nav } from "../components/Nav";
import { ParkedBanner } from "../components/ParkedBanner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Pics | Searchable memories",
  description: "A private, searchable photo library",
};

export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <header className="topbar">
            <Link className="brand" href="/">pics.</Link>
            <Nav />
          </header>
          <ParkedBanner />
          {children}
        </div>
      </body>
    </html>
  );
}
