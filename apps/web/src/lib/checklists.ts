export type ChecklistItem = {
  id: string;
  title: string;
  quantity: string;
  done: boolean;
};
export type ChecklistContent = {
  title: string;
  note: string;
  items: ChecklistItem[];
  archived: boolean;
};
export type Checklist = ChecklistContent & {
  id: string;
  version: number;
  updated_by: string;
  updated_at: string;
};
