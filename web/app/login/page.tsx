"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { LocaleToggle } from "@/components/LocaleToggle";
import { useLocale } from "@/components/LocaleProvider";
import * as api from "@/lib/api";
import { setToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { t } = useLocale();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [orgName, setOrgName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const auth =
        mode === "login" ? await api.login({ email, password }) : await api.register({ org_name: orgName, email, password });
      setToken(auth.session_token);
      router.push("/dashboard/events");
    } catch (err) {
      setError(err instanceof api.ApiError ? err.message : t("error.generic"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-[100dvh] flex flex-col p-6">
      <div className="flex justify-end">
        <LocaleToggle />
      </div>
      <form onSubmit={handleSubmit} className="flex-1 flex flex-col justify-center gap-4 max-w-sm mx-auto w-full">
        <h1 className="text-2xl font-bold text-center mb-2">
          {mode === "login" ? t("auth.login_title") : t("auth.register_title")}
        </h1>

        {mode === "register" && (
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-neutral-700">{t("auth.org_name")}</span>
            <input
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              className="rounded-lg border border-neutral-300 px-3 py-2"
              required
            />
          </label>
        )}

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">{t("auth.email")}</span>
          <input
            type="email"
            dir="ltr"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-lg border border-neutral-300 px-3 py-2"
            required
          />
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-neutral-700">{t("auth.password")}</span>
          <input
            type="password"
            dir="ltr"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded-lg border border-neutral-300 px-3 py-2"
            required
            minLength={mode === "register" ? 8 : undefined}
          />
        </label>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="mt-2 w-full rounded-full bg-neutral-900 py-3 text-sm font-semibold text-white disabled:opacity-60 active:scale-[0.98] transition"
        >
          {submitting ? t("auth.submitting") : mode === "login" ? t("auth.login_submit") : t("auth.register_submit")}
        </button>

        <button
          type="button"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
          className="text-sm text-neutral-500 underline"
        >
          {mode === "login" ? t("auth.switch_to_register") : t("auth.switch_to_login")}
        </button>
      </form>
    </div>
  );
}
