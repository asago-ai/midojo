export function getSessionToken(): string {
	const token = process.env.MIDOJO_SESSION_TOKEN;
	if (!token) throw new Error("No MiDojo evaluation session. Set MIDOJO_SESSION_TOKEN.");
	return token;
}
