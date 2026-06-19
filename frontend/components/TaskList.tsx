"use client";

import { Task } from "@/lib/types";

import { StatusBadge } from "./StatusBadge";

interface Props {
  tasks: Task[];
  loading: boolean;
  error: string | null;
  onDelete: (id: string) => void;
}

export function TaskList({ tasks, loading, error, onDelete }: Props) {
  if (error) {
    return (
      <div className="rounded-lg border bg-red-50 p-4 text-sm text-red-700">
        {error}
      </div>
    );
  }

  if (loading && tasks.length === 0) {
    return (
      <div className="rounded-lg border bg-white p-8 text-center text-sm text-slate-500">
        Loading tasks…
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="rounded-lg border bg-white p-8 text-center text-sm text-slate-500">
        No tasks yet. Create one to get started.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr>
            <th className="px-4 py-2">Title</th>
            <th className="px-4 py-2">Status</th>
            <th className="px-4 py-2">Retries</th>
            <th className="px-4 py-2">Scheduled</th>
            <th className="px-4 py-2">Last error</th>
            <th className="px-4 py-2"></th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {tasks.map((t) => (
            <tr key={t.id} className="align-top">
              <td className="px-4 py-2">
                <div className="font-medium">{t.title}</div>
                <div className="font-mono text-xs text-slate-400">{t.id}</div>
              </td>
              <td className="px-4 py-2">
                <StatusBadge status={t.status} />
              </td>
              <td className="px-4 py-2 tabular-nums">{t.retry_count}</td>
              <td className="px-4 py-2 text-xs text-slate-600">
                {new Date(t.scheduled_at).toLocaleString()}
              </td>
              <td className="max-w-xs px-4 py-2 text-xs text-red-600">
                {t.last_error ?? "—"}
              </td>
              <td className="px-4 py-2">
                <button
                  onClick={() => onDelete(t.id)}
                  className="text-xs text-slate-400 hover:text-red-600"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
