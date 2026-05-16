import Link from "next/link";

type Size = "sm" | "md" | "lg";

const mark: Record<Size, string> = {
  sm: "h-8 w-8 text-[10px] rounded-lg",
  md: "h-9 w-9 text-xs rounded-xl",
  lg: "h-11 w-11 text-sm rounded-xl",
};

export function LogoMark({ size = "md", className = "" }: { size?: Size; className?: string }) {
  return (
    <span
      className={`grid shrink-0 place-items-center bg-brand font-semibold tracking-tight text-white shadow-elev-1 ${mark[size]} ${className}`}
      aria-hidden
    >
      CF
    </span>
  );
}

export function Logo({
  size = "md",
  withWordmark = true,
  className = "",
}: {
  size?: Size;
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <LogoMark size={size} />
      {withWordmark ? (
        <span className="text-[15px] font-semibold tracking-tight text-ink sm:text-base">
          Confam
        </span>
      ) : null}
    </div>
  );
}

export function LogoLink({
  size = "md",
  className = "",
}: {
  size?: Size;
  className?: string;
}) {
  return (
    <Link
      href="/"
      className={`group flex items-center gap-2.5 rounded-xl outline-none ring-brand/25 transition hover:opacity-90 focus-visible:ring-2 ${className}`}
    >
      <Logo size={size} />
    </Link>
  );
}
