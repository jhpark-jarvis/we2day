"use server";
import type { AgentConnection } from "@/components/agent-connections";
import { callApi } from "@/lib/api";

export async function agentConnections() {
  return callApi<AgentConnection[]>("/agent-connections");
}
export async function createAgentConnection(label: string) {
  return callApi<AgentConnection & { key: string }>("/agent-connections", {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}
export async function revokeAgentConnection(id: string) {
  if (!/^[0-9a-f-]{36}$/i.test(id)) return { error: "연결을 확인해 주세요." };
  return callApi(`/agent-connections/${id}`, { method: "DELETE" });
}
