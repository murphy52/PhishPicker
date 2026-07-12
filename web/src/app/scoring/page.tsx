import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "How scoring works — Phishpicker",
  description:
    "The rules of the prediction game: Foresight vs Live ledgers, the point ladder, combos, bustouts, and PPPS.",
};

/** One row of a point ladder table. */
function LadderRow({
  event,
  points,
  note,
  accent,
}: {
  event: string;
  points: string;
  note?: string;
  accent: "foresight" | "live";
}) {
  return (
    <li className="flex items-baseline justify-between gap-3 border-b border-neutral-900 py-2 last:border-b-0">
      <span className="text-sm text-neutral-300">
        {event}
        {note && <span className="block text-xs text-neutral-500">{note}</span>}
      </span>
      <span
        className={`font-score shrink-0 text-lg font-extrabold ${
          accent === "foresight" ? "text-foresight" : "text-live"
        }`}
      >
        {points}
      </span>
    </li>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-neutral-800/80 bg-neutral-900/40 px-4 py-4">
      <h2 className="font-score mb-3 text-sm font-extrabold uppercase tracking-[0.2em] text-neutral-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function ScoringPage() {
  return (
    <div className="flex min-h-dvh flex-col bg-neutral-950 text-neutral-100">
      <header className="flex items-center justify-between px-4 pt-6">
        <Link
          href="/score"
          className="text-sm text-neutral-500 hover:text-neutral-300"
        >
          ← back
        </Link>
        <h1 className="font-score text-lg font-extrabold uppercase tracking-[0.3em]">
          How Scoring Works
        </h1>
        <span className="w-12" />
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 px-4 py-6 pb-16">
        <p className="text-sm text-neutral-400">
          Phishpicker scores <em>itself</em> — how well the app predicts each
          show, both before the lights go down and live as the setlist unfolds.
          Every actual song can earn points exactly once, through one of two
          ledgers.
        </p>

        <Section title="🔮 Foresight — the frozen bracket">
          <p className="mb-3 text-sm text-neutral-400">
            At show start the app freezes its full predicted setlist — one song
            per slot. That bracket never changes during the night. Each pick is
            scored by the best placement it achieved:
          </p>
          <ul>
            <LadderRow
              accent="foresight"
              event="Predicted song played somewhere"
              note="right song, wrong set"
              points="+5"
            />
            <LadderRow
              accent="foresight"
              event="Right set, wrong position"
              points="+15"
            />
            <LadderRow
              accent="foresight"
              event="Exact slot"
              note="same set and same position within it"
              points="+80"
            />
            <LadderRow
              accent="foresight"
              event="Exact slot and it's a set opener"
              note="S1.1, S2.1, or the first encore song — the showiest call in the game. Second/third-encore openers score plain exact (+80)."
              points="+100"
            />
          </ul>
        </Section>

        <Section title="⚡ Live — the next-song call">
          <p className="mb-3 text-sm text-neutral-400">
            After every song, the app calls what comes next. If its #1 pick is
            the actual next song, that&apos;s a live catch:
          </p>
          <ul>
            <LadderRow
              accent="live"
              event="Next-song call, exact"
              note="multiplied by the combo meter below"
              points="+30"
            />
            <LadderRow
              accent="live"
              event="🔭 Called it early"
              note="the app had it placed 2+ slots ahead — badge only"
              points="+0"
            />
          </ul>
          <p className="mt-3 text-xs text-neutral-500">
            The opener is never a live event — live calling starts after the
            first song, which is why the pre-show opener pick carries the
            biggest Foresight prize.
          </p>
        </Section>

        <Section title="Best claim wins">
          <p className="text-sm text-neutral-400">
            A song the app both foresaw <em>and</em> called live banks only the
            larger of the two base values — never both. Ties go to Foresight.
            Since a well-placed pick (+80/+100) beats a live call (+30), Live
            earns its keep on the songs the bracket missed or mis-placed. The
            feed always shows the claim that lost, so you can see the math.
          </p>
          <p className="mt-2 text-xs text-neutral-500">
            A song played twice (a sandwich) is matched once per occurrence —
            each bracket pick can claim only one, best first. Tweezer and
            Tweezer Reprise are separate songs and score independently.
          </p>
        </Section>

        <Section title="Combo meter">
          <p className="mb-3 text-sm text-neutral-400">
            Consecutive correct next-song calls build a streak, whichever
            ledger banks the song:
          </p>
          <ul>
            <LadderRow accent="live" event="First call in a row" points="×1" />
            <LadderRow accent="live" event="Second in a row" points="×1.5" />
            <LadderRow
              accent="live"
              event="Third and beyond"
              note="capped so a hot run never outshines the opener prize"
              points="×2"
            />
          </ul>
          <p className="mt-3 text-xs text-neutral-500">
            The multiplier pays only on Live-banked points — a foreseen song
            advances the meter but keeps its Foresight value. A wrong call
            resets the streak to 0; a gap in the capture (no call recorded)
            neither advances nor resets it.
          </p>
        </Section>

        <Section title="🎸 Bustouts & misses">
          <p className="text-sm text-neutral-400">
            A genuine bustout or debut is a celebration, not a failure: it
            scores 0 in both ledgers with no penalty, and it&apos;s excluded from
            the fairness metric below. It does break the streak, though — it
            was still a missed next-song call. A plain miss (a predictable song
            the app just didn&apos;t see coming) stays on the books.
          </p>
        </Section>

        <Section title="The numbers on the board">
          <dl className="flex flex-col gap-2 text-sm">
            <div>
              <dt className="font-semibold text-neutral-200">Combined</dt>
              <dd className="text-neutral-400">
                Foresight total + Live total — the hero number.
              </dd>
            </div>
            <div>
              <dt className="font-semibold text-neutral-200">PPPS</dt>
              <dd className="text-neutral-400">
                Points per predictable song — the combined total divided by the
                number of songs the app could reasonably have called (bustouts
                excluded, plain misses included). This is the fair way to
                compare a 15-song show to a 20-song one.
              </dd>
            </div>
            <div>
              <dt className="font-semibold text-neutral-200">Streak</dt>
              <dd className="text-neutral-400">
                The longest run of consecutive correct next-song calls in the
                show.
              </dd>
            </div>
          </dl>
        </Section>

        <Section title="Corrections & fine print">
          <p className="text-sm text-neutral-400">
            Scores are recomputed from captured data, never from a re-run of
            the model — what you were shown live is what gets scored. When
            phish.net corrects a setlist, the board recomputes and marks the
            changed song with a labeled ↻ rather than silently moving points.
            Soundcheck songs are never predicted and never scored.
          </p>
        </Section>
      </main>
    </div>
  );
}
