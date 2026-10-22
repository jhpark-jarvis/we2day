export type CoupleQuestion = {
  id: string;
  date: string;
  prompt: string;
  created_by: string;
  created_at: string;
};
export type Answer = {
  question_id: string;
  author_id: string;
  content: string;
  shared: boolean;
  skipped: boolean;
  version: number;
  updated_at: string;
};
export type QuestionView = {
  question: CoupleQuestion;
  mine: Answer | null;
  partner: Answer | null;
};
