import type { Metadata, Viewport } from "next";
import { Fredoka, Manrope, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/Nav";
import { Footer } from "@/components/Footer";
import { WalletProvider } from "@/components/WalletProvider";

const display = Fredoka({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-display", display: "swap" });
const body = Manrope({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-body", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "RugBond", template: "%s · RugBond" },
  description: "A token team bonds GEN behind a frozen liquidity promise. Pull the liquidity early and the bond pays the holders. Decided by code on GenLayer.",
  icons: { icon: "/logo.svg", apple: "/logo.svg" },
};
export const viewport: Viewport = { themeColor: "#0b0b0f", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>
        <a href="#main" className="small" style={{ position: "absolute", left: -9999 }}>Skip to content</a>
        <WalletProvider>
          <div className="wrap"><Nav /></div>
          <main id="main" className="wrap">{children}</main>
          <Footer />
        </WalletProvider>
      </body>
    </html>
  );
}
