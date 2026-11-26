export function VerdictBadge({ verdict, layer }: { verdict: string; layer?: string }) {
  const block = verdict === "block";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-mono font-medium border ${
        block ? "bg-block/10 text-block border-block/30" : "bg-ok/10 text-ok border-ok/25"
      }`}
    >
      {block ? "BLOCK" : "ALLOW"}
      {layer && <span className="opacity-70">· {layer}</span>}
    </span>
  );
}

export function LayerTag({ layer }: { layer?: string }) {
  const c = (layer === "regex" || layer === "layer1") ? "text-[#5eead4] border-[#5eead4]/30"
    : (layer === "layer2" || layer === "classifier") ? "text-[#818cf8] border-[#818cf8]/30"
    : (layer === "layer3" || layer === "judge" || layer === "policy_gate") ? "text-[#a78bfa] border-[#a78bfa]/30"
    : "text-muted border-line";
  const label = (layer === "regex" || layer === "layer1") ? "L1 Funnel"
    : (layer === "layer2" || layer === "classifier") ? "L2 Intent"
    : (layer === "layer3" || layer === "judge" || layer === "policy_gate") ? "L3 Policy"
    : layer ?? "—";
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[10.5px] font-mono ${c}`}>{label}</span>;
}

export function Panel({ title, right, children, className = "", bodyClass = "p-4" }: {
  title?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`sl-panel ${className}`}>
      {title && <div className="sl-panel-head"><span>{title}</span>{right && <span className="normal-case tracking-normal">{right}</span>}</div>}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}
