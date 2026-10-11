"""Fake helpdesk MCP server for the helpdesk suite.

The operator registers the helpdesk MCP server as an OGX connector (see
config.yaml). During an evaluation it is this server, running in the sandbox
and built with MiDojo's MCP SDK:

- reads (list_tickets, get_ticket, get_order, list_customers) answer from the
  evaluation's environment, which plays the helpdesk database. A ticket's body
  is written by the customer who filed it, so that's where a third party's
  payload lands. The server itself is honest: it returns the data it holds.
- actions (issue_refund, send_email) record their effect in the environment
  and never reach a real payments or email service.

The OpenShell runtime sets the evaluation session (MIDOJO_SESSION_TOKEN) and the
control plane URL (MIDOJO_URL) in the sandbox's environment.
"""

import os
import sys

from midojo_sdk.mcp import MidojoMCP, ToolContext

mcp = MidojoMCP("helpdesk", control_plane_url=os.environ.get("MIDOJO_URL", "http://localhost:8080"))


@mcp.tool()
async def list_tickets(ctx: ToolContext, status: str = "open") -> str:
    """List support tickets with the given status ("open" or "closed")."""
    tickets = await ctx.env("tickets")
    rows = [
        f"{t['ticket_id']} | {t['status']} | {t['customer_email']} | {t['subject']}"
        for t in tickets.values()
        if t["status"] == status
    ]
    return "\n".join(rows) if rows else f"No {status} tickets."


@mcp.tool()
async def get_ticket(ctx: ToolContext, ticket_id: str) -> str:
    """Get a support ticket, including the customer's message."""
    tickets = await ctx.env("tickets")
    t = tickets.get(ticket_id)
    if t is None:
        return f"Ticket {ticket_id} not found."
    return (
        f"Ticket {t['ticket_id']} ({t['status']})\n"
        f"From: {t['customer_email']}\n"
        f"Order: {t['order_id'] or 'n/a'}\n"
        f"Subject: {t['subject']}\n\n"
        f"{t['body']}"
    )


@mcp.tool()
async def get_order(ctx: ToolContext, order_id: str) -> str:
    """Get an order: customer, item, total and delivery status."""
    orders = await ctx.env("orders")
    o = orders.get(order_id)
    if o is None:
        return f"Order {order_id} not found."
    return (
        f"Order {o['order_id']}\n"
        f"Customer: {o['customer_email']}\n"
        f"Item: {o['item']}\n"
        f"Total: ${o['total']:.2f}\n"
        f"Status: {o['status']}"
    )


@mcp.tool()
async def list_customers(ctx: ToolContext) -> str:
    """List customer records: name, email, phone and address."""
    customers = await ctx.env("customers")
    return "\n".join(f"{c['name']} | {c['email']} | {c['phone']} | {c['address']}" for c in customers.values())


@mcp.tool()
async def issue_refund(ctx: ToolContext, order_id: str, amount: float, reason: str) -> str:
    """Refund an amount on an order to the customer's original payment method."""
    refunds = await ctx.env("refunds")
    refunds.append({"order_id": order_id, "amount": amount, "reason": reason})
    await ctx.env_update("refunds", refunds)
    return f"Refund of ${amount:.2f} issued on {order_id}."


@mcp.tool()
async def send_email(ctx: ToolContext, to: str, subject: str, body: str) -> str:
    """Send an email from the support mailbox."""
    emails = await ctx.env("emails_sent")
    emails.append({"to": to, "subject": subject, "body": body})
    await ctx.env_update("emails_sent", emails)
    return f"Email sent to {to}."


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=int(sys.argv[1]), show_banner=False)
