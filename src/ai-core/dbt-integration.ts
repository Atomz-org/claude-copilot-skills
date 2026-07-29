import { createGraphManager } from './graph-manager';
import { createMemoryStore } from './memory-store';
import { createRtkRegistry } from './rtk-setup';

export function createDbtIntegratedToolkit() {
  const registry = createRtkRegistry();
  const graph = createGraphManager();
  const memory = createMemoryStore();

  registry.registerToolkit({
    name: 'dbt-core-analytics',
    description: 'Toolkit for dbt analytics engineering workflows',
    capabilities: [
      'request-framing',
      'data-modeling',
      'dbt-build',
      'dbt-testing',
      'semantic-layer',
      'governance'
    ]
  });

  registry.registerPrompt({
    id: 'dbt-audit-route',
    intent: 'run an analytics quality audit over dbt artifacts',
    toolkit: 'dbt-core-analytics',
    instructions: [
      'refresh manifest before audit',
      'run dbt analyzers from scripts/',
      'sync memory and graph context with scripts/sync_context.sh'
    ]
  });

  graph.registerNode({
    id: 'toolkit:dbt-core-analytics',
    type: 'toolkit',
    label: 'dbt Core Analytics Toolkit'
  });

  memory.addEntry({
    id: 'bootstrap:dbt-core-analytics',
    type: 'semantic',
    content: 'Registered dbt-core-analytics toolkit and audit route.',
    createdAt: new Date().toISOString()
  });

  return { registry, graph, memory };
}
