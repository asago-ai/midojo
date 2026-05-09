/**
 * Direct tool execution through a real PI agent session.
 *
 * Creates an agent session with extensions loaded (which installs hooks),
 * then executes tool calls through the beforeToolCall → tool.execute() →
 * afterToolCall pipeline — same path as the agent loop, minus the LLM.
 */

import type { AgentSession } from "@mariozechner/pi-coding-agent";
import type { AgentToolCall, AfterToolCallContext, BeforeToolCallContext } from "@mariozechner/pi-agent-core";
import type { AssistantMessage } from "@mariozechner/pi-ai";

export interface ToolCallSpec {
	name: string;
	args: Record<string, unknown>;
}

export interface ToolCallResult {
	name: string;
	result: string;
	error?: string | null;
}

const ZERO_USAGE = {
	input: 0,
	output: 0,
	cacheRead: 0,
	cacheWrite: 0,
	totalTokens: 0,
	cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};

function makeSyntheticAssistantMessage(toolCall: AgentToolCall): AssistantMessage {
	return {
		role: "assistant",
		content: [toolCall],
		api: "anthropic",
		provider: "anthropic",
		model: "synthetic",
		stopReason: "toolUse",
		usage: ZERO_USAGE,
		timestamp: Date.now(),
	};
}

export async function executeTool(
	session: AgentSession,
	spec: ToolCallSpec,
): Promise<ToolCallResult> {
	const tool = session.agent.state.tools.find((t) => t.name === spec.name);
	if (!tool) {
		return { name: spec.name, result: "", error: `Tool not found: ${spec.name}` };
	}

	const toolCallId = `check-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
	const toolCall: AgentToolCall = {
		type: "toolCall",
		id: toolCallId,
		name: spec.name,
		arguments: spec.args,
	};
	const assistantMessage = makeSyntheticAssistantMessage(toolCall);
	const context = {
		systemPrompt: "",
		messages: [],
		tools: session.agent.state.tools,
	};

	// 1. beforeToolCall (fires tool_call extension hooks)
	if (session.agent.beforeToolCall) {
		const beforeCtx: BeforeToolCallContext = {
			assistantMessage,
			toolCall,
			args: spec.args,
			context,
		};
		const beforeResult = await session.agent.beforeToolCall(beforeCtx);
		if (beforeResult?.block) {
			return {
				name: spec.name,
				result: "",
				error: beforeResult.reason || "Blocked by hook",
			};
		}
	}

	// 2. tool.execute()
	let result: { content: Array<{ type: string; text?: string }>; details?: unknown };
	let isError = false;
	try {
		result = await tool.execute(toolCallId, spec.args);
	} catch (e) {
		const msg = e instanceof Error ? e.message : String(e);
		return { name: spec.name, result: msg, error: msg };
	}

	// 3. afterToolCall (fires tool_result extension hooks)
	let finalContent = result.content;
	if (session.agent.afterToolCall) {
		const afterCtx: AfterToolCallContext = {
			assistantMessage,
			toolCall,
			args: spec.args,
			result,
			isError,
			context,
		};
		const afterResult = await session.agent.afterToolCall(afterCtx);
		if (afterResult?.content) {
			finalContent = afterResult.content;
		}
		if (afterResult?.isError) {
			isError = true;
		}
	}

	const text = finalContent
		.filter((c): c is { type: "text"; text: string } => c.type === "text" && "text" in c)
		.map((c) => c.text)
		.join("\n");

	return {
		name: spec.name,
		result: text,
		error: isError ? text : null,
	};
}

export async function executeTools(
	session: AgentSession,
	specs: ToolCallSpec[],
): Promise<ToolCallResult[]> {
	const results: ToolCallResult[] = [];
	for (const spec of specs) {
		results.push(await executeTool(session, spec));
	}
	return results;
}
