import { encodeToon, type ToonValue } from './toon-serializer';

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  metadata?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
}

export class GraphManager {
  private nodes: GraphNode[] = [];
  private edges: GraphEdge[] = [];

  registerNode(node: GraphNode): void {
    this.nodes.push(node);
  }

  registerEdge(edge: GraphEdge): void {
    this.edges.push(edge);
  }

  snapshot(): { nodes: GraphNode[]; edges: GraphEdge[] } {
    return { nodes: this.nodes, edges: this.edges };
  }

  /**
   * Snapshot serialized as TOON for LLM context. Uniform node/edge rows encode
   * tabular (fields declared once); `metadata` is omitted because per-row
   * optional keys break tabular eligibility — fetch it per node when needed.
   */
  snapshotToToon(): string {
    const doc = {
      nodes: this.nodes.map(({ id, type, label }) => ({ id, type, label })),
      edges: this.edges.map(({ source, target, relation }) => ({ source, target, relation })),
    };
    return encodeToon(doc as ToonValue);
  }
}

export function createGraphManager(): GraphManager {
  const manager = new GraphManager();
  manager.registerNode({ id: 'repo:root', type: 'repository', label: 'Repository Root' });
  return manager;
}
