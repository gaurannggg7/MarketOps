import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { E2E_PASSWORDS } from "../playwright.config";

export const OPERATOR = { email: "operator@marketops.local", password: E2E_PASSWORDS.DEMO_OPERATOR_PASSWORD };
export const VIEWER = { email: "viewer@marketops.local", password: E2E_PASSWORDS.DEMO_VIEWER_PASSWORD };

export async function login(page: Page, who: { email: string; password: string }): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Password").fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Stream live")).toBeVisible({ timeout: 15_000 });
}

/** CSRF token for direct API calls made with the page's cookie jar. */
export async function csrf(request: APIRequestContext): Promise<string> {
  const r = await request.get("/api/v1/auth/session");
  const body = (await r.json()) as { session: { csrf_token: string } | null };
  if (!body.session) throw new Error("not signed in");
  return body.session.csrf_token;
}

export async function instrumentBySymbol(request: APIRequestContext, index: number): Promise<{ id: string; symbol: string }> {
  const r = await request.get("/api/v1/instruments?limit=1000");
  const body = (await r.json()) as { items: { id: string; symbol: string }[] };
  const item = body.items.at(index);
  if (!item) throw new Error(`no instrument at ${index}`);
  return item;
}
