"use client";

import type { FormEvent, ReactNode } from "react";
import {
  Suspense,
  useCallback,
  useEffect,
  useId,
  useState,
} from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AnimatePresence,
  motion,
  useReducedMotion,
} from "framer-motion";

import { useAuth } from "@/contexts/auth-context";
import { Logo } from "@/components/confam/Logo";
import { IconWallet, IconShield, IconChat } from "@/components/confam/icons";

/* -------------------------------------------------------------------------- */
/*                               Motion presets                                */
/* -------------------------------------------------------------------------- */

const fadeUp = {
  hidden: { opacity: 0, y: 18 },
  visible: { opacity: 1, y: 0 },
};

const stagger = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.08, delayChildren: 0.06 },
  },
};

type AuthMode = "signup" | "login";

/* -------------------------------------------------------------------------- */
/*                                 Buttons                                     */
/* -------------------------------------------------------------------------- */

type ButtonProps = {
  children: ReactNode;
  onClick?: () => void;
  type?: "button" | "submit";
  variant?: "primary" | "ghost" | "outline";
  disabled?: boolean;
  loading?: boolean;
  className?: string;
};

function Button({
  children,
  onClick,
  type = "button",
  variant = "primary",
  disabled,
  loading,
  className = "",
}: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:pointer-events-none disabled:opacity-50";
  const styles = {
    primary:
      "bg-brand text-white shadow-soft hover:bg-brand-dark active:scale-[0.98]",
    ghost: "text-brand hover:bg-white/70 active:bg-white",
    outline:
      "border border-mist-line bg-white text-ink hover:border-brand/35 hover:bg-mist active:scale-[0.98]",
  }[variant];

  const spinnerClass =
    variant === "primary"
      ? "border-white/40 border-t-white"
      : "border-mist-line border-t-brand";

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={`${base} ${styles} ${className}`}
    >
      {loading ? (
        <span className="flex items-center gap-2">
          <span
            className={`h-4 w-4 animate-spin rounded-full border-2 ${spinnerClass}`}
            aria-hidden
          />
          <span>Please wait…</span>
        </span>
      ) : (
        children
      )}
    </button>
  );
}

/* -------------------------------------------------------------------------- */
/*                              Mock price card                                */
/* -------------------------------------------------------------------------- */

function MockPriceCard() {
  const rows = [
    { label: "Pepper", value: "₦200" },
    { label: "Tomatoes", value: "₦600" },
    { label: "Seller Price", value: "₦1200", highlight: "warn" as const },
    {
      label: "Suggested Negotiation",
      value: "₦800–₦900",
      highlight: "good" as const,
    },
  ];

  return (
    <div className="w-full max-w-sm rounded-2xl border border-mist-line bg-white p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
          Sample check
        </p>
        <span className="rounded-full bg-mist px-2.5 py-0.5 text-[11px] font-semibold text-ink-muted">
          Today
        </span>
      </div>
      <div className="space-y-3">
        {rows.map((row) => (
          <div
            key={row.label}
            className="flex items-center justify-between gap-3 text-sm"
          >
            <span className="text-ink-muted">{row.label}</span>
            <span
              className={
                row.highlight === "warn"
                  ? "font-semibold text-amber-800"
                  : row.highlight === "good"
                    ? "font-semibold text-brand"
                    : "font-medium text-ink"
              }
            >
              {row.value}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-4 rounded-xl bg-mist px-3 py-2 text-center text-[11px] font-medium text-ink-muted">
        Illustrative snapshot — your assistant updates with context.
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*                               Feature card                                  */
/* -------------------------------------------------------------------------- */

type FeatureCardProps = {
  icon: ReactNode;
  title: string;
  description: string;
};

function FeatureCard({ icon, title, description }: FeatureCardProps) {
  const reduce = useReducedMotion();

  return (
    <motion.article
      variants={fadeUp}
      whileHover={
        reduce
          ? undefined
          : { y: -6, transition: { type: "spring", stiffness: 320, damping: 22 } }
      }
      className="group relative overflow-hidden rounded-2xl border border-mist-line bg-white p-6 shadow-card transition-shadow hover:shadow-elev-1"
    >
      <div className="mb-4 inline-flex h-11 w-11 items-center justify-center rounded-xl border border-mist-line bg-mist-paper text-brand">
        {icon}
      </div>
      <h3 className="text-base font-semibold tracking-tight text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-ink-muted">
        {description}
      </p>
    </motion.article>
  );
}

/* -------------------------------------------------------------------------- */
/*                               Step card                                     */
/* -------------------------------------------------------------------------- */

type StepCardProps = { step: string; title: string; body: string };

function StepCard({ step, title, body }: StepCardProps) {
  return (
    <motion.div
      variants={fadeUp}
      className="relative rounded-2xl border border-mist-line bg-white p-6 shadow-card"
    >
      <span className="mb-3 inline-flex h-8 min-w-[2rem] items-center justify-center rounded-lg bg-brand text-xs font-bold text-white shadow-soft">
        {step}
      </span>
      <h3 className="text-base font-semibold tracking-tight text-ink">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-ink-muted">{body}</p>
    </motion.div>
  );
}

/* -------------------------------------------------------------------------- */
/*                              Section wrapper                                */
/* -------------------------------------------------------------------------- */

function Section({
  id,
  className,
  children,
}: {
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  const reduce = useReducedMotion();

  return (
    <motion.section
      id={id}
      initial={reduce ? false : "hidden"}
      whileInView={reduce ? undefined : "visible"}
      viewport={{ once: true, margin: "-80px" }}
      variants={fadeUp}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      {children}
    </motion.section>
  );
}

/* -------------------------------------------------------------------------- */
/*                            Auth modal (signup / login)                      */
/* -------------------------------------------------------------------------- */

type AuthModalProps = {
  open: boolean;
  onClose: () => void;
  mode: AuthMode;
  onModeChange: (mode: AuthMode) => void;
  onAuthed: () => void;
};

function AuthModal({
  open,
  onClose,
  mode,
  onModeChange,
  onAuthed,
}: AuthModalProps) {
  const reduce = useReducedMotion();
  const titleId = useId();
  const { login, signup, error, clearFeedback } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [localSuccess, setLocalSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    clearFeedback();
    setLocalSuccess(null);
  }, [open, clearFeedback]);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  const backdrop = {
    hidden: { opacity: 0 },
    visible: { opacity: 1 },
  };

  const panel = {
    hidden: reduce
      ? { opacity: 0 }
      : { opacity: 0, scale: 0.96, y: 10 },
    visible: reduce
      ? { opacity: 1 }
      : { opacity: 1, scale: 1, y: 0 },
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    const email = String(fd.get("email") ?? "").trim();
    const password = String(fd.get("password") ?? "");

    setSubmitting(true);
    setLocalSuccess(null);
    try {
      if (mode === "signup") {
        const fullName = String(fd.get("fullName") ?? "").trim();
        await signup(fullName, email, password);
        setLocalSuccess("Account created. Redirecting…");
      } else {
        await login(email, password);
        setLocalSuccess("Signed in. Redirecting…");
      }
      window.setTimeout(() => {
        onAuthed();
        form.reset();
      }, 450);
    } catch {
      /* error surfaced via context */
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AnimatePresence mode="wait">
      {open ? (
        <motion.div
          key="auth-shell"
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <motion.button
            type="button"
            aria-label="Close dialog"
            className="absolute inset-0 bg-ink/40 backdrop-blur-[2px]"
            variants={backdrop}
            initial="hidden"
            animate="visible"
            exit="hidden"
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="relative z-10 w-full max-w-md rounded-2xl border border-mist-line bg-white p-6 shadow-elev-2 sm:mx-4 md:p-8"
            variants={panel}
            initial="hidden"
            animate="visible"
            exit="hidden"
            transition={{ type: "spring", stiffness: 380, damping: 28 }}
          >
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                <h2
                  id={titleId}
                  className="text-xl font-semibold tracking-tight text-ink"
                >
                  {mode === "signup"
                    ? "Create your Confam account"
                    : "Sign in to Confam"}
                </h2>
                <p className="mt-1 text-sm leading-relaxed text-ink-muted">
                  {mode === "signup"
                    ? "Join thousands negotiating with confidence."
                    : "Welcome back — pick up where you left off."}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-2 text-ink-muted transition hover:bg-mist hover:text-ink"
                aria-label="Close"
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden
                >
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            {error ? (
              <p
                className="mb-4 rounded-xl border border-amber-200/80 bg-amber-50/90 px-3 py-2.5 text-sm font-medium text-amber-950"
                role="alert"
              >
                {error}
              </p>
            ) : null}
            {localSuccess ? (
              <p
                className="mb-4 rounded-xl border border-brand/20 bg-brand/5 px-3 py-2 text-sm font-medium text-brand"
                role="status"
              >
                {localSuccess}
              </p>
            ) : null}

            <form className="space-y-4" onSubmit={handleSubmit}>
              {mode === "signup" ? (
                <div>
                  <label
                    htmlFor="cf-full-name"
                    className="mb-1.5 block text-xs font-medium text-ink-muted"
                  >
                    Full Name
                  </label>
                  <input
                    id="cf-full-name"
                    name="fullName"
                    required
                    autoComplete="name"
                    placeholder="Amina Okafor"
                    className="w-full rounded-xl border border-mist-line bg-white px-3 py-2.5 text-sm text-ink outline-none ring-brand/15 transition placeholder:text-ink-muted/60 focus:border-brand/45 focus:ring-2"
                  />
                </div>
              ) : null}
              <div>
                <label
                  htmlFor="cf-email"
                  className="mb-1.5 block text-xs font-medium text-ink-muted"
                >
                  Email
                </label>
                <input
                  id="cf-email"
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  placeholder="you@example.com"
                  className="w-full rounded-xl border border-mist-line bg-white px-3 py-2.5 text-sm text-ink outline-none ring-brand/15 transition placeholder:text-ink-muted/60 focus:border-brand/45 focus:ring-2"
                />
              </div>
              <div>
                <label
                  htmlFor="cf-password"
                  className="mb-1.5 block text-xs font-medium text-ink-muted"
                >
                  Password
                </label>
                <input
                  id="cf-password"
                  name="password"
                  type="password"
                  required
                  autoComplete={
                    mode === "signup" ? "new-password" : "current-password"
                  }
                  placeholder={
                    mode === "signup"
                      ? "At least 8 characters"
                      : "Your password"
                  }
                  minLength={mode === "signup" ? 8 : 1}
                  className="w-full rounded-xl border border-mist-line bg-white px-3 py-2.5 text-sm text-ink outline-none ring-brand/15 transition placeholder:text-ink-muted/60 focus:border-brand/45 focus:ring-2"
                />
              </div>

              <Button type="submit" className="w-full py-3" loading={submitting}>
                {mode === "signup" ? "Create Account" : "Sign in"}
              </Button>
            </form>

            <p className="mt-4 text-center text-sm text-ink-muted">
              {mode === "signup" ? (
                <>
                  Already have an account?{" "}
                  <button
                    type="button"
                    className="font-semibold text-brand underline-offset-4 transition hover:underline"
                    onClick={() => {
                      clearFeedback();
                      onModeChange("login");
                    }}
                  >
                    Sign in
                  </button>
                </>
              ) : (
                <>
                  New to Confam?{" "}
                  <button
                    type="button"
                    className="font-semibold text-brand underline-offset-4 transition hover:underline"
                    onClick={() => {
                      clearFeedback();
                      onModeChange("signup");
                    }}
                  >
                    Create an account
                  </button>
                </>
              )}
            </p>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

/* -------------------------------------------------------------------------- */
/*                                Page layout                                  */
/* -------------------------------------------------------------------------- */

function LandingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, loading, logout } = useAuth();
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<AuthMode>("signup");
  const reduce = useReducedMotion();

  const openSignup = useCallback(() => {
    setModalMode("signup");
    setModalOpen(true);
  }, []);

  const openLogin = useCallback(() => {
    setModalMode("login");
    setModalOpen(true);
  }, []);

  const closeModal = useCallback(() => setModalOpen(false), []);

  const onAuthed = useCallback(() => {
    closeModal();
    router.push("/chat");
  }, [closeModal, router]);

  const scrollToFeatures = useCallback(() => {
    document.getElementById("features")?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (searchParams.get("login") !== "1") return;
    setModalMode("login");
    setModalOpen(true);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("login");
      window.history.replaceState({}, "", `${url.pathname}${url.search}`);
    }
  }, [searchParams]);

  return (
    <div className="relative overflow-x-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-gradient-to-b from-white via-mist to-mist"
        aria-hidden
      />

      <header className="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
        <Link href="/" className="rounded-xl outline-none ring-brand/20 focus-visible:ring-2">
          <Logo />
        </Link>
        <nav className="hidden items-center gap-8 text-[13px] font-medium text-ink-muted sm:flex">
          <a className="transition hover:text-ink" href="#features">
            Product
          </a>
          <a className="transition hover:text-ink" href="#how-it-works">
            Flow
          </a>
          <a className="transition hover:text-ink" href="#footer">
            Company
          </a>
        </nav>
        <div className="flex min-h-[42px] items-center gap-2">
          {loading ? (
            <span
              className="inline-block h-10 w-28 animate-pulse rounded-xl bg-mist-line/80"
              aria-hidden
            />
          ) : user ? (
            <>
              <Button
                variant="ghost"
                className="hidden sm:inline-flex"
                type="button"
                onClick={() => router.push("/chat")}
              >
                Assistant
              </Button>
              <Button variant="outline" type="button" onClick={() => logout()}>
                Sign out
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                className="hidden sm:inline-flex"
                type="button"
                onClick={openLogin}
              >
                Sign in
              </Button>
              <Button onClick={openSignup}>Get Started</Button>
            </>
          )}
        </div>
      </header>

      <main className="relative z-10">
        <div className="mx-auto grid max-w-6xl gap-12 px-4 pb-20 pt-4 sm:px-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:gap-16 lg:px-8 lg:pb-28 lg:pt-2">
          <motion.div
            initial={reduce ? false : "hidden"}
            animate="visible"
            variants={stagger}
            className="max-w-xl"
          >
            <motion.p
              variants={fadeUp}
              className="mb-4 inline-flex items-center gap-2 rounded-full border border-mist-line bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted shadow-sm"
            >
              Built for Nigeria
            </motion.p>
            <motion.h1
              variants={fadeUp}
              className="text-balance text-4xl font-semibold tracking-tight text-ink sm:text-5xl lg:text-[3.1rem] lg:leading-[1.08]"
            >
              Spend with clarity. Negotiate with confidence.
            </motion.h1>
            <motion.p
              variants={fadeUp}
              className="mt-5 max-w-lg text-base leading-relaxed text-ink-muted sm:text-lg"
            >
              Confam is your calm companion for open-market prices and everyday transfers — fast checks, clear ranges, and safer payment context.
            </motion.p>
            <motion.div
              variants={fadeUp}
              className="mt-8 flex flex-wrap items-center gap-3"
            >
              {!user ? (
                <Button onClick={openSignup} className="px-6 py-3 text-base">
                  Get Started
                </Button>
              ) : (
                <Button
                  onClick={() => router.push("/chat")}
                  className="px-6 py-3 text-base"
                >
                  Open assistant
                </Button>
              )}
              <Button
                variant="outline"
                className="px-6 py-3 text-base"
                type="button"
                onClick={scrollToFeatures}
              >
                View sample prices
              </Button>
            </motion.div>
            <motion.p
              variants={fadeUp}
              className="mt-6 text-sm text-ink-muted"
            >
              Trusted by shoppers who want receipts, not guesswork.
            </motion.p>
          </motion.div>

          <motion.div
            initial={reduce ? false : { opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="relative flex justify-center lg:justify-end"
          >
            <div className="absolute -inset-3 -z-10 rounded-[1.75rem] bg-mist shadow-inner" />
            <MockPriceCard />
          </motion.div>
        </div>

        <Section
          id="features"
          className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:px-8 lg:py-24"
        >
          <div className="mx-auto max-w-2xl text-center">
            <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
              Product
            </p>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
              Everything you need before you pay.
            </h2>
            <p className="mt-3 text-ink-muted">
              One calm surface for prices, photos, voice, and transfer checks — built for real Nigerian commerce.
            </p>
          </div>
          <motion.div
            initial={reduce ? false : "hidden"}
            whileInView={reduce ? undefined : "visible"}
            viewport={{ once: true, margin: "-60px" }}
            variants={stagger}
            className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3"
          >
            <FeatureCard
              icon={<IconWallet className="h-6 w-6" />}
              title="Fair price bands"
              description="Know what stalls are charging this week — produce, provisions, and more — before you step in."
            />
            <FeatureCard
              icon={<IconShield className="h-6 w-6" />}
              title="Safer transfers"
              description="Read bank screenshots, double-check names, and keep a clean record of who you pay — without leaving the chat."
            />
            <FeatureCard
              icon={<IconChat className="h-6 w-6" />}
              title="Assistant on your side"
              description="Text, voice, or photo — get concise answers tuned for Nigerian markets and everyday money moves."
            />
          </motion.div>
        </Section>

        <Section
          id="how-it-works"
          className="border-y border-mist-line bg-white/85 py-16 backdrop-blur-[6px] sm:py-20 lg:py-24"
        >
          <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-2xl text-center">
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-muted">
                Flow
              </p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
                Three steps. Smarter buys.
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-ink-muted">
                From stall to transfer — the same calm surface, tuned for speed on mobile.
              </p>
            </div>
            <motion.div
              initial={reduce ? false : "hidden"}
              whileInView={reduce ? undefined : "visible"}
              viewport={{ once: true, margin: "-60px" }}
              variants={stagger}
              className="mt-12 grid gap-6 md:grid-cols-3"
            >
              <StepCard
                step="1"
                title="Search a product"
                body="Type what you need — groceries, provisions, gadgets — in plain language."
              />
              <StepCard
                step="2"
                title="See fair market price"
                body="Get a realistic range based on recent market activity and seasonal trends."
              />
              <StepCard
                step="3"
                title="Negotiate confidently"
                body="Use suggested counters so you stay firm without burning the sale."
              />
            </motion.div>
          </div>
        </Section>
      </main>

      <footer
        id="footer"
        className="relative z-10 border-t border-mist-line bg-white"
      >
        <div className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-12 sm:flex-row sm:items-start sm:justify-between sm:px-6 lg:px-8">
          <div>
            <Logo />
            <p className="mt-3 max-w-xs text-sm leading-relaxed text-ink-muted">
              Fair prices for real markets — negotiate smarter with Confam.
            </p>
          </div>
          <div className="flex flex-wrap gap-8 text-sm font-medium text-ink-muted">
            <a className="transition hover:text-brand" href="#">
              About
            </a>
            <a className="transition hover:text-brand" href="#">
              Contact
            </a>
            <a className="transition hover:text-brand" href="#">
              Privacy Policy
            </a>
          </div>
        </div>
        <div className="border-t border-mist-line/70 bg-mist/40">
          <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-2 px-4 py-4 text-xs text-ink-muted sm:flex-row sm:items-center sm:px-6 lg:px-8">
            <span>© {new Date().getFullYear()} Confam. All rights reserved.</span>
            <span>Lagos • Abuja • Port Harcourt — Nigeria</span>
          </div>
        </div>
      </footer>

      <AuthModal
        open={modalOpen}
        onClose={closeModal}
        mode={modalMode}
        onModeChange={setModalMode}
        onAuthed={onAuthed}
      />
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-mist">
          <div className="mx-auto flex max-w-6xl items-center justify-between border-b border-mist-line bg-white/90 px-4 py-4 sm:px-6">
            <Logo />
            <div className="h-9 w-28 animate-pulse rounded-full bg-mist-line" />
          </div>
          <div className="mx-auto mt-20 max-w-xl space-y-4 px-4 sm:px-6">
            <div className="h-12 w-[72%] max-w-md animate-pulse rounded-xl bg-mist-line" />
            <div className="h-4 w-full animate-pulse rounded-lg bg-mist-line/70" />
            <div className="h-4 w-5/6 animate-pulse rounded-lg bg-mist-line/60" />
          </div>
        </div>
      }
    >
      <LandingContent />
    </Suspense>
  );
}
