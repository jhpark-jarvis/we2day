import { type AgentConnection, AgentConnections } from "@/components/agent-connections";
import { PageHeading } from "@/components/page-heading";
import { callApi } from "@/lib/api";
import { getAuthConfig } from "@/lib/auth/config";

export const metadata = { title: "에이전트 연결" };
export default async function AgentSettings() {
  const result = await callApi<AgentConnection[]>("/agent-connections");
  return (
    <>
      <PageHeading>
        <div>
          <p className="eyebrow">AGENT CONNECTION</p>
          <h1>에이전트 연결</h1>
        </div>
      </PageHeading>
      <AgentConnections
        initial={result.data || []}
        initialError={result.error}
        endpoint={`${getAuthConfig()?.site || ""}/api/agent/v1`}
      />
    </>
  );
}
