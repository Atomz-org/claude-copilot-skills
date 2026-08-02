export interface MemoryEntry {
  id: string;
  type: 'episodic' | 'semantic';
  content: string;
  createdAt: string;
}

export class MemoryStore {
  private entries: MemoryEntry[] = [];

  addEntry(entry: MemoryEntry): void {
    this.entries.push(entry);
  }

  listEntries(): MemoryEntry[] {
    return this.entries;
  }

  search(query: string): MemoryEntry[] {
    return this.entries.filter((entry) => entry.content.toLowerCase().includes(query.toLowerCase()));
  }
}

export function createMemoryStore(): MemoryStore {
  return new MemoryStore();
}

// AgentMemory (rohitg00/agentmemory) REST adapter.
//
// The server is a user-level service on :3111 and is never a dependency of this
// module: every call is timeout-guarded and failure returns an empty/false result
// instead of throwing, so a checkout without AgentMemory behaves exactly as before.

export interface AgentMemoryOptions {
  baseUrl?: string;
  timeoutMs?: number;
}

export class AgentMemoryClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(options: AgentMemoryOptions = {}) {
    this.baseUrl = (options.baseUrl ?? 'http://127.0.0.1:3111').replace(/\/+$/, '');
    this.timeoutMs = options.timeoutMs ?? 1000;
  }

  async health(): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseUrl}/agentmemory/health`, {
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  async remember(content: string, concepts: string[] = []): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseUrl}/agentmemory/remember`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, concepts }),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  async recall(query: string, limit = 5): Promise<MemoryEntry[]> {
    try {
      const res = await fetch(`${this.baseUrl}/agentmemory/smart-search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, limit }),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      if (!res.ok) {
        return [];
      }
      return normalizeSearchResults(await res.json());
    } catch {
      return [];
    }
  }
}

function normalizeSearchResults(data: unknown): MemoryEntry[] {
  const record = data as { results?: unknown[]; memories?: unknown[] } | unknown[] | null;
  const rows = Array.isArray(record)
    ? record
    : Array.isArray(record?.results)
      ? record.results
      : Array.isArray(record?.memories)
        ? record.memories
        : [];
  return rows.map((raw, index): MemoryEntry => {
    const row = raw as Record<string, unknown>;
    return {
      id: String(row.id ?? row.obsId ?? index),
      type: row.type === 'episodic' ? 'episodic' : 'semantic',
      content: String(row.content ?? row.text ?? row.memory ?? row.title ?? JSON.stringify(row)),
      createdAt: String(row.createdAt ?? row.created_at ?? row.timestamp ?? ''),
    };
  });
}

export class BridgedMemoryStore {
  private readonly local = new MemoryStore();
  private readonly client: AgentMemoryClient;

  constructor(client: AgentMemoryClient) {
    this.client = client;
  }

  async addEntry(entry: MemoryEntry): Promise<void> {
    this.local.addEntry(entry);
    await this.client.remember(entry.content, [entry.type]);
  }

  listEntries(): MemoryEntry[] {
    return this.local.listEntries();
  }

  async search(query: string): Promise<MemoryEntry[]> {
    const remote = await this.client.recall(query);
    return remote.length > 0 ? remote : this.local.search(query);
  }
}

export async function createBridgedMemoryStore(
  options: AgentMemoryOptions = {},
): Promise<BridgedMemoryStore | MemoryStore> {
  const client = new AgentMemoryClient(options);
  return (await client.health()) ? new BridgedMemoryStore(client) : createMemoryStore();
}
