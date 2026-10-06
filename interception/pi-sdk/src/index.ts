import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
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

export interface MidojoToolHook {
	toolName: string;
	execute: (
		args: Record<string, unknown>,
		realResult: string,
		ctx: ToolContext,
	) => Promise<string>;
}

export interface MidojoExtensionConfig {
	controlPlaneUrl: string;
	tools?: MidojoToolDef[];
	hooks?: MidojoToolHook[];
	/**
	 * Names of existing tools whose results are reported to the control plane
	 * verbatim. Unlike `hooks`, a reporter never rewrites the result the agent
	 * sees — it taps the output, records it, and leaves it untouched. Use this to
	 * make a tool's result (e.g. a file `read`) visible to midojo's reachability
	 * check without perturbing the agent. Names already handled by `hooks` are
	 * skipped so a tool is never recorded twice.
	 */
	reportTools?: string[];
	/**
	 * Names of tools that never run. When the agent calls one, the call is
	 * recorded to the control plane as blocked and the agent gets an error
	 * instead of a result. Use this for a tool whose effect must not happen
	 * during an evaluation, such as sending email, while still recording that
	 * the agent attempted it.
	 */
	blockTools?: string[];
}

/** What the agent is told when it calls a tool in `blockTools`: PI's own message for a blocked call. */
export const BLOCKED_REASON = "Tool execution was blocked";

/** Read the evaluation process's session token from the environment on every request. */
export class ControlPlaneClient {
	private baseUrl: string;

	constructor(baseUrl: string | undefined = process.env.MIDOJO_URL) {
		if (!baseUrl) throw new Error("MiDojo control plane URL is required. Set MIDOJO_URL or configure controlPlaneUrl.");
		let end = baseUrl.length;
		while (end > 0 && baseUrl[end - 1] === "/") end--;
		this.baseUrl = `${baseUrl.slice(0, end)}/agent`;
	}

	private getSessionToken(): string {
		const token = process.env.MIDOJO_SESSION_TOKEN;
		if (!token) throw new Error("No MiDojo evaluation session. Set MIDOJO_SESSION_TOKEN.");
		return token;
	}

	private async request(path: string, method: string = "GET", body?: unknown): Promise<Response> {
		const resp = await fetch(`${this.baseUrl}${path}`, {
			method,
			headers: {
				"Content-Type": "application/json",
				"Authorization": `Bearer ${this.getSessionToken()}`,
			},
			body: body === undefined ? undefined : JSON.stringify(body),
		});
		if (!resp.ok) throw new Error(`MiDojo ${method} ${path} failed (${resp.status})`);
		return resp;
	}

	async getEnvironment(): Promise<Record<string, unknown>> {
		return (await this.request("/environment")).json() as Promise<Record<string, unknown>>;
	}

	async putEnvironment(env: Record<string, unknown>): Promise<void> {
		await this.request("/environment", "PUT", env);
	}

	async recordFunctionCall(entry: {
		function: string;
		args: Record<string, unknown>;
		result: string;
		error?: string | null;
		blocked?: boolean;
	}): Promise<void> {
		await this.request("/function-calls", "POST", entry);
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
		const client = new ControlPlaneClient(config.controlPlaneUrl);

		for (const toolDef of config.tools ?? []) {
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

		for (const hook of config.hooks ?? []) {
			pi.on("tool_result", async (event) => {
				if (event.toolName !== hook.toolName) return;

				const ctx = client.createToolContext();
				const realResult = event.content
					.filter((c): c is { type: "text"; text: string } => c.type === "text")
					.map((c) => c.text)
					.join("\n");

				let result: string;
				let error: string | null = null;
				try {
					result = await hook.execute(event.input, realResult, ctx);
				} catch (e) {
					error = e instanceof Error ? e.message : String(e);
					result = error;
				}

				await client.recordFunctionCall({
					function: hook.toolName,
					args: event.input,
					result,
					error,
				});

				return {
					content: [{ type: "text" as const, text: result }],
				};
			});
		}

		// Passive reporters: record a tool's result to the control plane without
		// altering it. Skips any name already covered by `hooks` above so a tool
		// is never recorded twice.
		const hookedTools = new Set((config.hooks ?? []).map((h) => h.toolName));
		for (const reportToolName of new Set(config.reportTools ?? [])) {
			if (hookedTools.has(reportToolName)) continue;
			pi.on("tool_result", async (event) => {
				if (event.toolName !== reportToolName) return;

				const result = event.content
					.filter((c): c is { type: "text"; text: string } => c.type === "text")
					.map((c) => c.text)
					.join("\n");

				await client.recordFunctionCall({
					function: reportToolName,
					args: event.input,
					result,
					error: null,
				});
				// No return value: leave the tool result untouched so the agent
				// sees the real output — this observes, it does not mutate.
			});
		}

		// Blocked tools: record the attempted call, then stop it. PI skips
		// tool_result for a blocked call, so the hooks and reporters above never
		// see it. If recording fails, the error blocks the call too.
		const blockedTools = new Set(config.blockTools ?? []);
		if (blockedTools.size > 0) {
			pi.on("tool_call", async (event) => {
				if (!blockedTools.has(event.toolName)) return;

				await client.recordFunctionCall({
					function: event.toolName,
					args: event.input as Record<string, unknown>,
					result: BLOCKED_REASON,
					blocked: true,
				});
				return { block: true, reason: BLOCKED_REASON };
			});
		}
	};
}
