export type TaskStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "dead";

export interface Task {
  id: string;
  title: string;
  payload: Record<string, unknown>;
  scheduled_at: string;
  status: TaskStatus;
  retry_count: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskListResponse {
  items: Task[];
  total: number;
  limit: number;
  offset: number;
}
