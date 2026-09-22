import { AsyncLocalStorage } from "node:async_hooks";

const sessions = new AsyncLocalStorage<string>();

/** Bind hooks and their async work to one task in a persistent agent. */
export function withMidojoSession<T>(token: string, fn: () => T): T {
	if (!token) throw new Error("MiDojo evaluation session token is required");
	return sessions.run(token, fn);
}

export function getSessionToken(): string {
	const token = sessions.getStore() || process.env.MIDOJO_SESSION_TOKEN;
	if (!token) throw new Error("No MiDojo evaluation session. Set MIDOJO_SESSION_TOKEN or use withMidojoSession().");
	return token;
}
