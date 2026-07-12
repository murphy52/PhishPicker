/**
 * Full-screen "rotate to portrait" block. Always in the DOM; CSS reveals it
 * only on a touch device held in landscape (see `.rotate-guard` in
 * globals.css). Phishpicker's single-column live UI is portrait-only, and iOS
 * ignores the manifest's `orientation` lock — this is the cross-platform guard.
 */
export function RotateGuard() {
  return (
    <div
      data-testid="rotate-guard"
      className="rotate-guard fixed inset-0 z-[100] flex-col items-center justify-center gap-3 bg-neutral-950 px-8 text-center text-neutral-100"
    >
      <span className="text-4xl" aria-hidden="true">
        📱
      </span>
      <p className="font-score text-lg font-extrabold uppercase tracking-[0.2em]">
        Rotate to portrait
      </p>
      <p className="text-sm text-neutral-500">
        Phishpicker is built for portrait — turn your phone upright.
      </p>
    </div>
  );
}
