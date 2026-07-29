export interface ToolkitRoute {
  name: string;
  description: string;
  capabilities: string[];
}

export interface PromptRoute {
  id: string;
  intent: string;
  toolkit: string;
  instructions: string[];
}

export class RtkRegistry {
  private routes: PromptRoute[] = [];
  private toolkits: ToolkitRoute[] = [];

  registerToolkit(toolkit: ToolkitRoute): void {
    this.toolkits.push(toolkit);
  }

  registerPrompt(route: PromptRoute): void {
    this.routes.push(route);
  }

  listToolkits(): ToolkitRoute[] {
    return this.toolkits;
  }

  listPrompts(): PromptRoute[] {
    return this.routes;
  }
}

export function createRtkRegistry(): RtkRegistry {
  const registry = new RtkRegistry();
  registry.registerToolkit({
    name: 'default',
    description: 'Baseline AI toolkit for repository automation',
    capabilities: ['planning', 'reasoning', 'documentation']
  });
  return registry;
}
