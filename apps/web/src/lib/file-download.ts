export async function downloadRecord(path: string, body: object, filename: string, type: string) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.timeout(25000),
  });
  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.error || "파일을 만들지 못했어요.");
  }
  if (!response.headers.get("content-type")?.startsWith(type))
    throw new Error("파일 형식을 확인하지 못했어요.");
  const file = await response.blob();
  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");
  try {
    anchor.href = url;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
  } finally {
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
