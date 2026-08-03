import type { Metadata } from "next";
import Script from "next/script";
import { loadPublicInstance } from "../instance";
import "./globals.css";

const CLOUDFLARE_ANALYTICS_TOKEN = process.env.CLOUDFLARE_ANALYTICS_SITE_TOKEN;

export function generateMetadata(): Metadata {
  const instance = loadPublicInstance();
  return {
    title: "Me-as-a-Service",
    description: `${instance.representation_label} for ${instance.display_name}.`,
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        {children}
        {CLOUDFLARE_ANALYTICS_TOKEN ? (
          <Script
            src="https://static.cloudflareinsights.com/beacon.min.js"
            data-cf-beacon={JSON.stringify({
              token: CLOUDFLARE_ANALYTICS_TOKEN,
            })}
            strategy="afterInteractive"
          />
        ) : null}
      </body>
    </html>
  );
}
