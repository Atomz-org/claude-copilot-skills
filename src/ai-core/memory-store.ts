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
