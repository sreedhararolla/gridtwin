import type { MemberCard as MemberCardData } from "@/lib/api";

// The member-facing Storm mode card: every sentence is rendered as the API wrote it from
// the Reserve Reasons (a template, no LLM).
export function MemberCard({ card, caption }: { card: MemberCardData; caption?: string }) {
  return (
    <div className="max-w-md rounded-lg border border-soc/40 bg-slate-900 p-4">
      {caption ? <p className="mb-1 text-xs text-slate-500">{caption}</p> : null}
      <h3 className="text-base font-semibold text-soc">{card.headline}</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-200">
        {card.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      <p className="mt-3 text-sm text-slate-300">{card.reserve}</p>
    </div>
  );
}
