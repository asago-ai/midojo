import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import type { TSchema } from "typebox";

export interface ToolContext {
	env<T = unknown>(field: string): Promise<T>;
	envUpdate(field: string, value: unknown): Promise<void>;
}

export interface MidojoToolDef {
	name: string;
	label: string;
	description: string;
	parameters: TSchema;
	execute: (params: Record<string, unknown>, ctx: ToolContext) => Promise<string>;
}

export interface MidojoExtensionConfig {
	controlPlaneUrl: string;
	runId: string;
	evalId: string;
	tools: MidojoToolDef[];
}

class ControlPlaneClient {
	private baseUrl: string;
	private envCache: Record<string, unknown> | null = null;

	constructor(baseUrl: string, runId: string, evalId: string) {
		const base = baseUrl.replace(/\/+$/, "");
		this.baseUrl = `${base}/runs/${runId}/evaluations/${evalId}`;
	}

	async getEnvironment(): Promise<Record<string, unknown>> {
		if (this.envCache) return this.envCache;
		const resp = await fetch(`${this.baseUrl}/environment`);
		if (!resp.ok) return {};
		this.envCache = (await resp.json()) as Record<string, unknown>;
		return this.envCache;
	}

	async putEnvironment(env: Record<string, unknown>): Promise<void> {
		this.envCache = env;
		await fetch(`${this.baseUrl}/environment`, {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(env),
		});
	}

	async recordFunctionCall(entry: { function: string; args: Record<string, unknown>; result: string; error?: string | null }): Promise<void> {
		await fetch(`${this.baseUrl}/function-calls`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(entry),
		}).catch(() => {});
	}

	createToolContext(): ToolContext {
		return {
			env: async <T = unknown>(field: string): Promise<T> => {
				const env = await this.getEnvironment();
				return env[field] as T;
			},
			envUpdate: async (field: string, value: unknown): Promise<void> => {
				const env = await this.getEnvironment();
				env[field] = value;
				await this.putEnvironment(env);
			},
		};
	}
}

export function createMidojoExtension(config: MidojoExtensionConfig): (pi: ExtensionAPI) => void {
	return (pi: ExtensionAPI) => {
		const client = new ControlPlaneClient(config.controlPlaneUrl, config.runId, config.evalId);

		for (const toolDef of config.tools) {
			pi.registerTool({
				name: toolDef.name,
				label: toolDef.label,
				description: toolDef.description,
				parameters: toolDef.parameters,
				async execute(_toolCallId, params) {
					const typedParams = params as Record<string, unknown>;
					const ctx = client.createToolContext();

					let result: string;
					let error: string | null = null;
					try {
						result = await toolDef.execute(typedParams, ctx);
					} catch (e) {
						error = e instanceof Error ? e.message : String(e);
						result = error;
					}

					await client.recordFunctionCall({
						function: toolDef.name,
						args: typedParams,
						result,
						error,
					});

					return {
						content: [{ type: "text" as const, text: result }],
						details: { tool: toolDef.name, params: typedParams },
					};
				},
			});
		}
	};
}
