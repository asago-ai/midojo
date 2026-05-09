#!/usr/bin/env npx tsx
/**
 * midojo-pi-check — execute tool calls through a PI agent session with hooks.
 *
 * Usage:
 *   npx tsx pi-sdk/src/cli.ts --agent-dir ./pi_agent --tools '[{"name":"get_weather","args":{"city":"New York"}}]'
 *
 * Outputs JSON array of results to stdout.
 */

import { createAgentSession } from "@mariozechner/pi-coding-agent";
import { executeTools, type ToolCallSpec } from "./execute.js";

async function main() {
	const args = process.argv.slice(2);

	let agentDir = process.cwd();
	let toolsJson = "";

	for (let i = 0; i < args.length; i++) {
		if (args[i] === "--agent-dir" && args[i + 1]) {
			agentDir = args[++i];
		} else if (args[i] === "--tools" && args[i + 1]) {
			toolsJson = args[++i];
		}
	}

	if (!toolsJson) {
		process.stderr.write("Usage: midojo-pi-check --agent-dir <dir> --tools '<json>'\n");
		process.exit(1);
	}

	let toolCalls: ToolCallSpec[];
	try {
		toolCalls = JSON.parse(toolsJson);
	} catch {
		process.stderr.write(`Invalid JSON for --tools: ${toolsJson}\n`);
		process.exit(1);
	}

	const { session } = await createAgentSession({
		cwd: agentDir,
		agentDir,
		noTools: "builtin",
	});

	try {
		const results = await executeTools(session, toolCalls);
		process.stdout.write(JSON.stringify(results) + "\n");
	} finally {
		session.dispose();
	}
}

main().catch((err) => {
	process.stderr.write(`Error: ${err}\n`);
	process.exit(1);
});
