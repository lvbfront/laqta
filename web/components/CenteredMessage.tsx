export function CenteredMessage({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "error";
}) {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center p-6 text-center">
      <p className={tone === "error" ? "text-red-600 font-medium" : "text-neutral-600"}>{children}</p>
    </div>
  );
}
