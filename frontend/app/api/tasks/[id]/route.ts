import { NextRequest, NextResponse } from "next/server";

import { backendFetch } from "@/lib/api";

// DELETE /api/tasks/{id} -> proxied delete
export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const res = await backendFetch(`/tasks/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (res.status === 204) {
    return new NextResponse(null, { status: 204 });
  }
  const body = await res.json();
  return NextResponse.json(body, { status: res.status });
}
