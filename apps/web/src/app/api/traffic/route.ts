import { unstable_cache } from "next/cache";
import { NextResponse } from "next/server";

const CLOUDFLARE_GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql";
const CACHE_SECONDS = 15 * 60;
const DAYS_TO_REPORT = 7;

type CloudflareAnalyticsResponse = {
  data?: {
    viewer?: {
      accounts?: Array<{
        pageViews?: Array<{ count?: unknown }>;
      }>;
    };
  };
  errors?: unknown[];
};

async function fetchPageViews(): Promise<number> {
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
  const hostname = process.env.MAAS_DOMAIN;
  const apiToken = process.env.CLOUDFLARE_ANALYTICS_API_TOKEN;
  if (!accountId || !hostname || !apiToken) {
    throw new Error("Cloudflare Analytics is not configured");
  }

  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - DAYS_TO_REPORT);

  const response = await fetch(CLOUDFLARE_GRAPHQL_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query: `
        query PageViews($accountTag: string!, $hostname: string!, $start: Time!, $end: Time!) {
          viewer {
            accounts(filter: { accountTag: $accountTag }) {
              pageViews: rumPageloadEventsAdaptiveGroups(
                filter: {
                  datetime_geq: $start
                  datetime_leq: $end
                  requestHost: $hostname
                }
                limit: 1
              ) {
                count
              }
            }
          }
        }
      `,
      variables: {
        accountTag: accountId,
        hostname,
        start: start.toISOString(),
        end: end.toISOString(),
      },
    }),
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) {
    throw new Error(`Cloudflare Analytics returned ${response.status}`);
  }

  const payload = (await response.json()) as CloudflareAnalyticsResponse;
  const pageViews = payload.data?.viewer?.accounts?.[0]?.pageViews;
  if (payload.errors?.length || !Array.isArray(pageViews)) {
    throw new Error("Cloudflare Analytics returned an invalid response");
  }

  if (pageViews.length === 0) {
    return 0;
  }

  const count = pageViews[0]?.count;
  if (typeof count !== "number" || count < 0) {
    throw new Error("Cloudflare Analytics returned an invalid response");
  }
  return count;
}

const getPageViews = unstable_cache(fetchPageViews, ["cloudflare-page-views"], {
  revalidate: CACHE_SECONDS,
});

export async function GET() {
  try {
    return NextResponse.json(
      { page_views: await getPageViews(), period_days: DAYS_TO_REPORT },
      {
        headers: {
          "Cache-Control": `public, max-age=0, s-maxage=${CACHE_SECONDS}, stale-while-revalidate=${CACHE_SECONDS}`,
        },
      },
    );
  } catch {
    return NextResponse.json(
      { detail: "Traffic data is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
