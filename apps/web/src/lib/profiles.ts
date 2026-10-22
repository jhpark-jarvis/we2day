export type Profile = {
  user_id: string;
  display_name: string;
  version: number;
  updated_at: string;
};

export type ProfileView = { mine: Profile | null; partner: Profile | null };

export function profileNames(view: ProfileView | null): Record<string, string> {
  return Object.fromEntries(
    [view?.mine, view?.partner].flatMap((profile) =>
      profile ? [[profile.user_id, profile.display_name]] : [],
    ),
  );
}
