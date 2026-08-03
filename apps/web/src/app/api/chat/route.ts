import { NextResponse } from "next/server";

const API_BASE_URL = process.env.MAAS_API_BASE_URL ?? "http://127.0.0.1:8000";
const PROXY_SHARED_SECRET = process.env.MAAS_PROXY_SHARED_SECRET;

function clientAddress(request: Request) {
  const forwardedFor = request.headers.get("x-forwarded-for");
  return forwardedFor?.split(",", 1)[0]?.trim();
}

export async function POST(request: Request) {
  try {
    const accept = request.headers.get("Accept");
    const address = clientAddress(request);
    const response = await fetch(`${API_BASE_URL}/api/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(accept ? { Accept: accept } : {}),
        ...(PROXY_SHARED_SECRET && address
          ? {
              "X-MaaS-Client-IP": address,
              "X-MaaS-Proxy-Secret": PROXY_SHARED_SECRET,
            }
          : {}),
      },
      body: await request.text(),
      cache: "no-store",
    });

    const contentType =
      response.headers.get("Content-Type") ?? "application/json";
    const proxyResponse = new NextResponse(response.body, {
      status: response.status,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": contentType,
      },
    });

    return proxyResponse;
  } catch {
    return NextResponse.json(
      { detail: "The evidence API is unavailable. Please try again." },
      { status: 502 },
    );
  }
}
