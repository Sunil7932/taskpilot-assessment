import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/api";

// GET /api/tasks?status=&limit=&offset=  -> proxied list
export async function GET(req: NextRequest) {
  const qs = req.nextUrl.searchParams.toString();
  const res = await backendFetch(`/tasks${qs ? `?${qs}` : ""}`);
  const body = await res.json();
  return NextResponse.json(body, { status: res.status });
}

// POST /api/tasks  -> proxied create
export async function POST(req: NextRequest) {
  let payload: unknown;
  try {
    payload = await req.json();
  } catch {
    return NextResponse.json(
      { error: { code: "invalid_json", message: "Request body is not valid JSON." } },
      { status: 400 },
    );
  }
  const res = await backendFetch("/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  const body = await res.json();
  return NextResponse.json(body, { status: res.status });
}
