export type QuestionSearchQuery = { start_date: string; end_date: string; query: string };
export type QuestionSearchHit = { id: string; date: string; prompt: string };
export type QuestionSearchPage = { items: QuestionSearchHit[]; next_offset: number | null };
