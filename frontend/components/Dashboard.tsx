"use client";

import { useCallback, useEffect, useState } from "react";

import { Task, TaskListResponse, TaskStatus } from "@/lib/types";

import { CreateTaskForm } from "./CreateTaskForm";
import { TaskList } from "./TaskList";

const STATUSES: (TaskStatus | "all")[] = [
  "all",
  "pending",
  "running",
  "succeeded",
  "failed",
  "dead",
];
const PAGE_SIZE = 10;
const POLL_MS = 5000;

export function Dashboard() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<TaskStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (status !== "all") params.set("status", status);

    try {
      const res = await fetch(`/api/tasks?${params.toString()}`);
      if (!res.ok) {
        setError(`Failed to load tasks (${res.status}).`);
        return;
      }
      const data: TaskListResponse = await res.json();
      setTasks(data.items);
      setTotal(data.total);
      setError(null);
    } catch {
      setError("Network error — is the API reachable?");
    } finally {
      setLoading(false);
    }
  }, [offset, status]);

  // Reload on filter/page change, then poll for live status updates.
  useEffect(() => {
    setLoading(true);
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  async function handleDelete(taskId: string) {
    await fetch(`/api/tasks/${taskId}`, { method: "DELETE" });
    load();
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="grid gap-6 md:grid-cols-[1fr_2fr]">
      <CreateTaskForm
        onCreated={() => {
          setOffset(0);
          load();
        }}
      />

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <select
            value={status}
            onChange={(e) => {
              setOffset(0);
              setStatus(e.target.value as TaskStatus | "all");
            }}
            className="rounded border bg-white px-2 py-1 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <span className="text-xs text-slate-500">{total} total</span>
        </div>

        <TaskList
          tasks={tasks}
          loading={loading}
          error={error}
          onDelete={handleDelete}
        />

        <div className="flex items-center justify-between text-sm">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded border px-3 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-slate-500">
            Page {page} of {pageCount}
          </span>
          <button
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded border px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
