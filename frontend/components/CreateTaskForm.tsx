"use client";

import { useState } from "react";

interface Props {
  onCreated: () => void;
}

export function CreateTaskForm({ onCreated }: Props) {
  const [title, setTitle] = useState("");
  const [payload, setPayload] = useState("{}");
  const [scheduledAt, setScheduledAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    let parsedPayload: unknown;
    try {
      parsedPayload = JSON.parse(payload || "{}");
    } catch {
      setError("Payload must be valid JSON.");
      return;
    }

    const body: Record<string, unknown> = { title, payload: parsedPayload };
    if (scheduledAt) body.scheduled_at = new Date(scheduledAt).toISOString();

    setSubmitting(true);
    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.error?.message ?? `Request failed (${res.status}).`);
        return;
      }
      setTitle("");
      setPayload("{}");
      setScheduledAt("");
      onCreated();
    } catch {
      setError("Network error — is the API reachable?");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded-lg border bg-white p-4 shadow-sm"
    >
      <h2 className="font-semibold">Create task</h2>

      <div>
        <label className="block text-sm font-medium">Title</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
          maxLength={255}
          placeholder="send receipt"
          className="mt-1 w-full rounded border px-3 py-2 text-sm"
        />
      </div>

      <div>
        <label className="block text-sm font-medium">Payload (JSON)</label>
        <textarea
          value={payload}
          onChange={(e) => setPayload(e.target.value)}
          rows={3}
          spellCheck={false}
          className="mt-1 w-full rounded border px-3 py-2 font-mono text-sm"
        />
        <p className="mt-1 text-xs text-slate-500">
          Tip: {`{"force_fail": true}`} makes the worker fail and retry.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium">
          Scheduled at (optional)
        </label>
        <input
          type="datetime-local"
          value={scheduledAt}
          onChange={(e) => setScheduledAt(e.target.value)}
          className="mt-1 rounded border px-3 py-2 text-sm"
        />
      </div>

      {error && (
        <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
      >
        {submitting ? "Creating…" : "Create task"}
      </button>
    </form>
  );
}
