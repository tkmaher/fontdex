import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "fonts-index API",
  description: "Created by otherseas1. https://otherseas1.com",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
