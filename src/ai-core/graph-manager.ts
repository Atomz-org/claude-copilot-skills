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
}

export function createGraphManager(): GraphManager {
  const manager = new GraphManager();
  manager.registerNode({ id: 'repo:root', type: 'repository', label: 'Repository Root' });
  return manager;
}
