import {
  buildOauthProviderAuthResult,
  emptyPluginConfigSchema,
  type OpenClawPluginApi,
  type ProviderAuthContext,
} from "openclaw/plugin-sdk";
import { loginOpenAICodex } from "@mariozechner/pi-ai";

const PROVIDER_ID = "openai-codex";
const DEFAULT_MODEL = "openai-codex/gpt-5.2-codex";

function extractUrlFromAuthPayload(payload: unknown): string {
  if (typeof payload === "string") {
    return payload.trim();
  }
  if (!payload || typeof payload !== "object") {
    return "";
  }
  const record = payload as Record<string, unknown>;
  if (typeof record.authUrl === "string" && record.authUrl.trim()) {
    return record.authUrl.trim();
  }
  if (typeof record.url === "string" && record.url.trim()) {
    return record.url.trim();
  }
  return "";
}

const openAiCodexOauthPlugin = {
  id: "maestro-openai-codex-auth",
  name: "Maestro OpenAI Codex Auth",
  description: "OpenAI Codex OAuth provider plugin used by Maestro quick setup.",
  configSchema: emptyPluginConfigSchema(),
  register(api: OpenClawPluginApi) {
    api.registerProvider({
      id: PROVIDER_ID,
      label: "OpenAI Codex OAuth",
      docsPath: "/providers/models",
      auth: [
        {
          id: "oauth",
          label: "OpenAI OAuth",
          hint: "Sign in with your ChatGPT/OpenAI account",
          kind: "oauth",
          run: async (ctx: ProviderAuthContext) => {
            const progress = ctx.prompter.progress("Starting OpenAI OAuth flow...");
            try {
              const creds = await loginOpenAICodex({
                onAuth: async (authPayload: unknown) => {
                  const url = extractUrlFromAuthPayload(authPayload);
                  if (!url) {
                    return;
                  }
                  await ctx.openUrl(url);
                },
                onPrompt: async (message: string) => {
                  const response = await ctx.prompter.text({ message });
                  return String(response);
                },
                onProgress: (message: string) => {
                  progress.update(message || "Waiting for OpenAI OAuth callback...");
                },
              });

              if (!creds?.access || !creds?.refresh) {
                throw new Error("OpenAI OAuth did not return valid credentials.");
              }

              progress.stop("OpenAI OAuth complete");
              return buildOauthProviderAuthResult({
                providerId: PROVIDER_ID,
                defaultModel: DEFAULT_MODEL,
                access: creds.access,
                refresh: creds.refresh,
                expires: creds.expires,
                email: creds.email,
              });
            } catch (error) {
              progress.stop("OpenAI OAuth failed");
              throw error;
            }
          },
        },
      ],
    });
  },
};

export default openAiCodexOauthPlugin;
