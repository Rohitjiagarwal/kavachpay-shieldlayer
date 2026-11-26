/** Brand marks. KavachPay = the payments app ("kavach" = armour). ShieldLayer = the security product. */

export const BRAND = {
  name: "KavachPay",
  tagline: "UPI payments with a built-in shield",
  assistant: "Kavi",
  assistantFull: "Kavi · Kavach Assist",
};

export function KavachMark({ size = 36, className = "" }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className={className} role="img" aria-label="KavachPay">
      <defs>
        <linearGradient id="kv-g" x1="6" y1="3" x2="34" y2="37" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#2dd4bf" />
          <stop offset=".55" stopColor="#4f46e5" />
          <stop offset="1" stopColor="#7c3aed" />
        </linearGradient>
        <linearGradient id="kv-h" x1="20" y1="3" x2="20" y2="22" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#fff" stopOpacity=".35" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M20 2.5 34.5 7.8V19c0 9.2-6.1 15.9-14.5 18.5C11.6 34.9 5.5 28.2 5.5 19V7.8L20 2.5Z" fill="url(#kv-g)" />
      <path d="M20 2.5 34.5 7.8V19c0 .8 0 1.6-.1 2.3C29 17 12 16 5.6 21.2 5.5 20.5 5.5 19.7 5.5 19V7.8L20 2.5Z" fill="url(#kv-h)" />
      <path d="M15.2 11.5v16.5M25 11.5l-8.6 8.2 8.9 8.3" stroke="#fff" strokeWidth="3.1" strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  );
}

export function KavachLogo({ size = 36, sub = true }: { size?: number; sub?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <KavachMark size={size} />
      <div className="leading-tight">
        <div className="font-bold tracking-tight text-[17px]">Kavach<span className="text-[#5eead4]">Pay</span></div>
        {sub && <div className="text-[10.5px] text-[var(--pn-muted)]">{BRAND.tagline}</div>}
      </div>
    </div>
  );
}

/** ShieldLayer: four nested shields, one per defence layer. */
export function ShieldLayerMark({ size = 32, className = "" }: { size?: number; className?: string }) {
  const d = "M20 2.5 34.5 7.8V19c0 9.2-6.1 15.9-14.5 18.5C11.6 34.9 5.5 28.2 5.5 19V7.8L20 2.5Z";
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" className={className} role="img" aria-label="ShieldLayer">
      {[1, 0.74, 0.5, 0.27].map((s, i) => (
        <path key={s} d={d} transform={`translate(${20 - 20 * s} ${20 - 20 * s}) scale(${s})`}
          fill={i === 3 ? "#22d3ee" : "none"} stroke="#22d3ee" strokeOpacity={1 - i * 0.2}
          strokeWidth={i === 0 ? 2 : 1.6} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
}
